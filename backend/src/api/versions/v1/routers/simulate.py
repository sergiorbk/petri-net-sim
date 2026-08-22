"""Standalone simulation endpoint — no session required."""

import asyncio
import json
import logging
from typing import Any

import httpx

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.shared.rate_limit import rate_limit
from src.core.dependencies import get_current_user
from src.core.security_config import security_settings
from src.domain.models import PetriNet
from src.infrastructure.postgres.models.user import User
from src.core.config import settings
from src.services.simulation.engine import PetriSimulator, SimulationLimitError
from src.services.simulation.limits import clean_net_data as _clean_net_data
from src.services.simulation.limits import validate_simulation_request as _validate_simulation_request
from src.services.simulation.remote import run_remote_streaming
from src.services.simulation.remote_error import remote_error_detail

_log = logging.getLogger(__name__)
_SSE_DONE = "data: [DONE]\n\n"

router = APIRouter(prefix="/simulate", tags=["simulation"])

# Per-user rate limit shared by both simulation endpoints.
_simulate_rate_limit = rate_limit(
    scope="simulate",
    max_requests=security_settings.RATE_LIMIT_SIMULATE_MAX,
    window_seconds=security_settings.RATE_LIMIT_SIMULATE_WINDOW,
    by="token",
)


def _simulation_error_message(exc: Exception, remote_url: str | None) -> str:
    # Resource-cap errors carry no sensitive detail and are actionable for the user.
    if isinstance(exc, SimulationLimitError):
        return str(exc)
    if remote_url and isinstance(exc, httpx.ConnectError):
        return f"Simulation backend is unavailable ({remote_url}). Check that the service is running."
    if remote_url and isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if 400 <= status < 500:
            detail = remote_error_detail(exc.response)
            if detail:
                return detail
        return f"Simulation backend returned an error: HTTP {status}."
    if remote_url and isinstance(exc, httpx.TimeoutException):
        return f"Simulation backend timed out ({remote_url})."
    if isinstance(exc, ValueError):
        # Raised by the exporter's own invariant checks (assert_invariants),
        # before any request ever reached a remote backend: an invalid element
        # id, a duplicate id, a cross-page arc. That is a problem with the
        # model, not with the deployment, so surface it verbatim instead of
        # burying it behind a generic "internal error" (mirrors how
        # simulate_composed.py's own _simulation_error_message treats a
        # ValueError as model, not transport, vocabulary).
        return str(exc)
    # Built-in engine failure: log full detail server-side, return a generic
    # message to the client to avoid leaking internals.
    _log.exception("Simulation failed")
    return "Simulation failed due to an internal error."


class StandaloneSimulateBody(BaseModel):
    """Request body for standalone simulation."""

    net_data: dict[str, Any] = Field(
        description="Full Petri net JSON to simulate.",
    )


@router.post(
    "",
    summary="Stream a simulation for an arbitrary Petri net",
    dependencies=[Depends(_simulate_rate_limit)],
)
async def simulate_standalone(  # NOSONAR
    simulation_time: float = Query(default=3600.0, gt=0, description="Simulation time units"),
    time_step: float = Query(
        default=1.0,
        gt=0,
        description=(
            "Time-based mode: emit a snapshot every this many simulation time units. "
            "Ignored when snapshot_interval is also set."
        ),
    ),
    snapshot_interval: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Scientific/step-based mode: emit a snapshot every N discrete transition "
            "firings. When set, overrides time_step."
        ),
    ),
    animation_delay: float = Query(
        default=0.0,
        ge=0.0,
        le=10.0,
        description="Real-time pause (seconds) inserted after each snapshot. 0 = stream as fast as possible.",
    ),
    body: StandaloneSimulateBody = Body(...),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream a discrete-event simulation for the provided Petri net.

    Unlike the session-scoped endpoint, this does not require or create a
    session.  The caller supplies the full net JSON in the request body.

    Returns ``text/event-stream`` chunks of shape
    ``{current_time, step_number, markings, buffers, progress, fired_transitions,
    firing_sequence}`` terminated by ``data: [DONE]``.  ``firing_sequence`` is
    the ordered list of atomic highlight steps since the previous frame; it is
    empty when nothing fired, or when a remote backend does not report phases.
    """
    net_data = _clean_net_data(body.net_data)
    _validate_simulation_request(net_data, simulation_time)

    if not net_data.get("places"):
        async def _empty():
            yield 'data: {"error": "No network to simulate. The net has no places."}\n\n'
            yield _SSE_DONE

        return StreamingResponse(
            _empty(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    net = PetriNet(**net_data)
    # None here means the deployment runs on the built-in engine; see
    # Settings.simulation_remote_target, which owns that choice.
    remote_url = settings.simulation_remote_target
    use_fallback = settings.SIMULATION_REMOTE_FALLBACK

    def _local_iter():
        return PetriSimulator(net).run_streaming(
            simulation_time,
            time_step=time_step,
            snapshot_interval=snapshot_interval,
        )

    async def _emit_events(event_iter, is_remote: bool):
        async for event in event_iter:
            payload = json.dumps({
                "current_time": event.current_time,
                "step_number": event.step_number,
                "markings": event.markings,
                "buffers": event.buffers,
                "progress": event.progress,
                "fired_transitions": event.fired_transitions,
                "firing_sequence": [
                    {
                        "transition_id": fs.transition_id,
                        "phase": fs.phase,
                        "markings": fs.markings,
                        "buffers": fs.buffers,
                        "time": fs.time,
                    }
                    for fs in event.firing_sequence
                ],
            })
            yield f"data: {payload}\n\n"
            if animation_delay > 0 and not is_remote:
                await asyncio.sleep(animation_delay)

    async def _stream():
        if not remote_url:
            try:
                async for chunk in _emit_events(_local_iter(), is_remote=False):
                    yield chunk
            except Exception as exc:
                yield f"data: {json.dumps({'error': _simulation_error_message(exc, None)})}\n\n"
            yield _SSE_DONE
            return

        frames_sent = 0
        try:
            async for chunk in _emit_events(
                run_remote_streaming(
                    net,
                    base_url=remote_url,
                    simulation_time=simulation_time,
                    time_step=time_step,
                    snapshot_interval=snapshot_interval,
                    animation_delay_ms=int(animation_delay * 1000),
                ),
                is_remote=True,
            ):
                frames_sent += 1
                yield chunk
        except httpx.ConnectError as exc:
            if use_fallback:
                _log.warning(
                    "Simulation backend unreachable (%s), falling back to built-in engine", remote_url
                )
                yield f"data: {json.dumps({'warning': f'Remote backend unavailable, using built-in engine'})}\n\n"
                try:
                    async for chunk in _emit_events(_local_iter(), is_remote=False):
                        yield chunk
                except Exception as fb_exc:
                    yield f"data: {json.dumps({'error': _simulation_error_message(fb_exc, None)})}\n\n"
            else:
                yield f"data: {json.dumps({'error': _simulation_error_message(exc, remote_url)})}\n\n"
        except Exception as exc:
            if frames_sent > 0:
                _log.warning(
                    "Simulation backend (%s) disconnected after %d frames — cannot fall back mid-stream",
                    remote_url, frames_sent,
                )
                yield f"data: {json.dumps({'error': f'Remote backend disconnected after {frames_sent} frames'})}\n\n"
            else:
                yield f"data: {json.dumps({'error': _simulation_error_message(exc, remote_url)})}\n\n"
        yield _SSE_DONE

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/precompute",
    summary="Pre-run a simulation and return all snapshots as JSON",
    dependencies=[Depends(_simulate_rate_limit)],
)
async def simulate_precompute(  # NOSONAR
    simulation_time: float = Query(default=3600.0, gt=0, description="Simulation time units"),
    time_step: float = Query(default=1.0, gt=0, description="Snapshot every this many sim units (time mode)"),
    snapshot_interval: int | None = Query(
        default=None,
        ge=1,
        description="Snapshot every N transition firings (scientific mode). Overrides time_step when set.",
    ),
    expand_phases: bool = Query(
        default=False,
        description=(
            "When true, each firing phase (act_in / act_out) becomes its own "
            "snapshot so the UI can animate one arc movement per step."
        ),
    ),
    body: StandaloneSimulateBody = Body(...),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Run the full simulation synchronously and return all snapshots as a JSON array.

    Unlike the streaming endpoint this response is a plain JSON object so the
    client knows the total snapshot count before starting playback.  Intended
    for stepped / manual-pacing playback where the UI must display ``X / N``.
    """
    net_data = _clean_net_data(body.net_data)
    _validate_simulation_request(net_data, simulation_time)
    if not net_data.get("places"):
        return {"snapshots": [], "total": 0}

    net = PetriNet(**net_data)
    simulator = PetriSimulator(net)
    max_snapshots = security_settings.SIMULATION_MAX_SNAPSHOTS

    snapshots: list[dict[str, Any]] = []

    if expand_phases:
        snapshots.append({
            "current_time": 0.0,
            "step_number": 0,
            "markings": {p.id: p.tokens for p in net.places},
            "buffers": {t.id: 0 for t in net.transitions},
            "progress": 0.0,
            "fired_transitions": [],
            "phase": "initial",
            "firing_sequence": [],
        })

    truncated = False
    try:
        async for event in simulator.run_streaming(
            simulation_time,
            time_step=time_step if snapshot_interval is None else None,
            snapshot_interval=snapshot_interval,
        ):
            if len(snapshots) >= max_snapshots:
                truncated = True
                _log.warning(
                    "Precompute snapshot cap reached (%d) — truncating response",
                    max_snapshots,
                )
                break
            if expand_phases and event.firing_sequence:
                seq = event.firing_sequence
                i = 0
                while i < len(seq) and len(snapshots) < max_snapshots:
                    fs = seq[i]
                    if fs.phase.startswith("before_") and i + 1 < len(seq):
                        after = seq[i + 1]
                        action = fs.phase.removeprefix("before_")
                        snapshots.append({
                            "current_time": fs.time,
                            "step_number": len(snapshots),
                            "markings": fs.markings,
                            "buffers": fs.buffers,
                            "markings_after": after.markings,
                            "buffers_after": after.buffers,
                            "progress": event.progress,
                            "fired_transitions": [fs.transition_id],
                            "phase": action,
                            "firing_sequence": [{
                                "transition_id": fs.transition_id,
                                "phase": action,
                                "markings": fs.markings,
                                "buffers": fs.buffers,
                                "markings_after": after.markings,
                                "buffers_after": after.buffers,
                                "time": fs.time,
                            }],
                        })
                        i += 2
                    else:
                        snapshots.append({
                            "current_time": fs.time,
                            "step_number": len(snapshots),
                            "markings": fs.markings,
                            "buffers": fs.buffers,
                            "progress": event.progress,
                            "fired_transitions": [fs.transition_id],
                            "phase": fs.phase,
                            "firing_sequence": [{
                                "transition_id": fs.transition_id,
                                "phase": fs.phase,
                                "markings": fs.markings,
                                "buffers": fs.buffers,
                                "time": fs.time,
                            }],
                        })
                        i += 1
                if len(snapshots) >= max_snapshots and i < len(seq):
                    truncated = True
                    _log.warning(
                        "Precompute snapshot cap reached (%d) during expand_phases — truncating",
                        max_snapshots,
                    )
                    break
            else:
                snapshots.append({
                    "current_time": event.current_time,
                    "step_number": event.step_number,
                    "markings": event.markings,
                    "buffers": event.buffers,
                    "progress": event.progress,
                    "fired_transitions": event.fired_transitions,
                    "firing_sequence": [
                        {
                            "transition_id": fs.transition_id,
                            "phase": fs.phase,
                            "markings": fs.markings,
                            "buffers": fs.buffers,
                            "time": fs.time,
                        }
                        for fs in event.firing_sequence
                    ],
                })
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"snapshots": snapshots, "total": len(snapshots), "truncated": truncated}
