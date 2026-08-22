"""Composed Petri-object model simulation API endpoints - V1.

New dedicated router rather than branching inside simulate.py/sessions.py:
the request shape is fundamentally different (multiple linked objects), and
those two files already duplicate a large SSE loop between them — a third
near-copy branching on model type would make both worse, not better.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from src.api.shared.exceptions import (
    BadRequestException,
    NotFoundException,
    ServiceUnavailableException,
)
from src.api.shared.rate_limit import rate_limit
from src.core.config import settings
from src.core.dependencies import get_current_user, get_postgres_session
from src.core.security_config import security_settings
from src.domain.composed import ComposedModel, LinkType
from src.domain.models import PetriNet
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.session_repository import SessionRepository
from src.services.petri.exporter import get_composed_pnml_exporter
from src.services.petri.importer import parse_pnml
from src.services.simulation.composed_engine import ComposedSimulationUnsupported, build_composed_sim_net
from src.services.simulation.engine import PetriSimulator
from src.services.simulation.limits import clean_net_data as _clean_net_data
from src.services.simulation.limits import validate_simulation_request as _validate_simulation_request
from src.services.simulation.remote_error import remote_error_detail
from src.services.simulation.remote_v2 import parse_composed_model_remote, run_remote_streaming_v2

_log = logging.getLogger(__name__)
_SSE_DONE = "data: [DONE]\n\n"

router = APIRouter(prefix="/simulate/composed", tags=["simulation-composed"])

# Shares the same "simulate" rate-limit scope/budget as the flat-net endpoints.
_simulate_rate_limit = rate_limit(
    scope="simulate",
    max_requests=security_settings.RATE_LIMIT_SIMULATE_MAX,
    window_seconds=security_settings.RATE_LIMIT_SIMULATE_WINDOW,
    by="token",
)


class ComposedObjectSpec(BaseModel):
    """One object in a composed-model request: either an inline flat net,
    or a reference to an existing session's net."""

    name: str | None = None
    priority: int = 0
    x: float = 0.0
    y: float = 0.0
    width: float | None = None
    height: float | None = None
    collapsed: bool = False
    parent: int | None = None
    auto_fit: bool | None = None
    free: bool = False
    net_data: dict[str, Any] | None = None
    session_id: str | None = None


class ComposedLinkSpec(BaseModel):
    type: str = Field(..., description="placeFusion | transitionToPlace | placeToTransition")
    source_object: int = Field(..., ge=0)
    source_element: int = Field(..., ge=0)
    target_object: int = Field(..., ge=0)
    target_element: int = Field(..., ge=0)
    quantity: int = Field(default=1, ge=1)
    informational: bool = False


class ComposedSimulateBody(BaseModel):
    name: str = "ComposedModel"
    objects: list[ComposedObjectSpec] = Field(
        ..., min_length=1, max_length=security_settings.SIMULATION_MAX_OBJECTS
    )
    links: list[ComposedLinkSpec] = Field(default_factory=list)


async def _resolve_composed_model(
    body: ComposedSimulateBody, user: User, session: AsyncSession
) -> ComposedModel:
    """Build a ComposedModel from inline net JSON and/or existing sessions.

    Feasibility note (not wired up here): this loop is its own independent
    ComposedObjectSpec -> ComposedModel parser, separate from
    services/petri/composed_convert.py's net_data <-> ComposedModel
    converter and from that module's newer
    composed_model_to_wire_objects (the inverse direction: ComposedModel ->
    wire-body-shaped object specs, added for the create_object cap/free-
    pool-omission alignment). Reusing composed_convert.py here would mean:
    each `spec.session_id`/`spec.net_data` branch still has to resolve to
    one flat net_data dict same as today (a single-session-id request has
    no `objects`/`links` structure of its own to hand this converter), so
    the actual saving is on the OTHER direction -- once a caller wants to
    submit a whole composed PetriNetSession's net_data as this endpoint's
    wire body in one shot, composed_model_to_wire_objects is what builds
    that objects[] list (parent indices remapped, an empty free pool
    dropped) instead of hand-partitioning it here. Not done in this change:
    no caller needs that shape yet, and this loop's per-object safety
    checks (_validate_simulation_request, the ValidationError ->
    BadRequestException translation) are request-shaped concerns that
    belong here regardless of where the object list came from.
    """
    repo = SessionRepository(session)
    model = ComposedModel(name=body.name)

    for index, spec in enumerate(body.objects):
        if spec.net_data is not None:
            net_data = _clean_net_data(spec.net_data)
        elif spec.session_id is not None:
            instance = await repo.get_by_id(spec.session_id)
            if instance is None or instance.user_id != user.id:
                raise NotFoundException(resource="Session", identifier=spec.session_id)
            net_data = _clean_net_data(instance.net_data or {})
        else:
            raise BadRequestException(
                "Each composed-model object needs either net_data or session_id"
            )

        # Same per-net safety caps the flat-net endpoints enforce (place/transition/arc
        # counts) — a composed model is just several of these, so each one must pass
        # individually. simulation_time isn't known here (irrelevant for /preview), so
        # pass 0.0 to skip that half of the check; simulate_composed() checks it separately.
        _validate_simulation_request(net_data, 0.0)

        try:
            net = PetriNet(**net_data)
        except ValidationError as exc:
            # A net the domain model refuses is this request's problem, not the
            # service's. Letting it out as an unhandled error answered with a
            # 500, which the canvas can only report as "the simulation service
            # is unavailable": true of nothing, and it hid the one sentence the
            # user could act on, such as which transition has a distribution it
            # cannot run with.
            raise BadRequestException(
                f"Object {index} ({spec.name or 'unnamed'}) is not a valid net: "
                + "; ".join(
                    f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
                    for err in exc.errors()
                )
            ) from exc

        model.add_object(
            net,
            name=spec.name,
            priority=spec.priority,
            x=spec.x,
            y=spec.y,
            width=spec.width,
            height=spec.height,
            collapsed=spec.collapsed,
            parent=spec.parent,
            auto_fit=spec.auto_fit,
            free=spec.free,
        )

    for link_spec in body.links:
        try:
            link_type = LinkType(link_spec.type)
        except ValueError as exc:
            raise BadRequestException(f"Unknown link type: '{link_spec.type}'") from exc
        model.add_link(
            link_type,
            source_object=link_spec.source_object,
            source_element=link_spec.source_element,
            target_object=link_spec.target_object,
            target_element=link_spec.target_element,
            quantity=link_spec.quantity,
            informational=link_spec.informational,
        )

    errors = model.validate()
    if errors:
        # Details must be shaped like the API's ValidationError (field +
        # message): the exception handler builds that model verbatim, and a
        # bare {"error": ...} used to crash it, burying the one message the
        # canvas user could actually act on under a plain 500.
        raise BadRequestException(
            "Composed model is invalid",
            details=[{"field": "model", "message": e} for e in errors],
        )

    return model


def _simulation_error_message(exc: Exception, remote_url: str | None) -> tuple[str, str]:
    """Message plus whose vocabulary it is in: "model" or "transport".

    A 4xx from petri-server is the engine rejecting THIS model, and its body
    carries the one message the canvas user can act on — swallowing it behind
    "HTTP 400" sent people debugging a healthy deployment. Everything else
    (unreachable, timeout, 5xx) is deployment vocabulary the frontend
    deliberately rewords.
    """
    if remote_url and isinstance(exc, httpx.ConnectError):
        return (
            f"Simulation backend is unavailable ({remote_url}). Check that the service is running.",
            "transport",
        )
    if remote_url and isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if 400 <= status < 500:
            detail = remote_error_detail(exc.response)
            if detail:
                return (detail, "model")
        return (f"Simulation backend returned an error: HTTP {status}.", "transport")
    if remote_url and isinstance(exc, httpx.TimeoutException):
        return (f"Simulation backend timed out ({remote_url}).", "transport")
    if isinstance(exc, ValueError):
        # A ValueError here was raised inside this process, before any request
        # ever reached petri-server: the composed PNML exporter's own
        # invariant checks (an invalid element id, a duplicate id, a cross-
        # page arc, ...), run at export time by `assert_invariants`. That is a
        # problem with the model, not with the deployment it is talking to, so
        # it carries "model" kind exactly like a 4xx rejection would.
        return (str(exc), "model")
    _log.exception("Composed simulation failed")
    return (f"Simulation error: {exc}", "transport")


@router.post(
    "",
    summary="Stream a simulation for a composed Petri-object model (v2)",
    dependencies=[Depends(_simulate_rate_limit)],
)
async def simulate_composed(
    simulation_time: float = Query(default=3600.0, gt=0, le=security_settings.SIMULATION_MAX_TIME),
    time_step: float = Query(default=1.0, gt=0),
    snapshot_interval: int | None = Query(default=None, ge=1),
    animation_delay: float = Query(default=0.0, ge=0.0, le=10.0),
    body: ComposedSimulateBody = Body(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> StreamingResponse:
    """
    Stream a discrete-event simulation for a composed Petri-object model.

    Mirrors the flat-net endpoint's remote/local split: with no
    ``SIMULATION_REMOTE_URL`` configured, or when it's unreachable and
    ``SIMULATION_REMOTE_FALLBACK`` is set, this runs on the built-in local
    engine (``build_composed_sim_net`` + ``PetriSimulator``) instead of
    petri-server. The one gap is placeToTransition links, which the local
    engine does not support (see ``ComposedSimulationUnsupported``) — a model
    using one always needs the remote engine.
    """
    model = await _resolve_composed_model(body, user, session)
    # None here means the deployment runs on the built-in engine; see
    # Settings.simulation_remote_target, which owns that choice.
    remote_url = settings.simulation_remote_target
    use_fallback = settings.SIMULATION_REMOTE_FALLBACK

    def _local_iter():
        places, transitions = build_composed_sim_net(model)
        return PetriSimulator.from_sim_state(places, transitions).run_streaming(
            simulation_time,
            time_step=time_step,
            snapshot_interval=snapshot_interval,
        )

    async def _emit_events(event_iter):
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

    def _local_error_frame(exc: Exception) -> str:
        if isinstance(exc, ComposedSimulationUnsupported):
            return json.dumps({"error": str(exc), "kind": "model"})
        _log.exception("Local composed simulation failed")
        return json.dumps({"error": f"Simulation error: {exc}", "kind": "transport"})

    async def _stream():
        if not remote_url:
            try:
                async for chunk in _emit_events(_local_iter()):
                    yield chunk
            except Exception as exc:
                yield f"data: {_local_error_frame(exc)}\n\n"
            yield _SSE_DONE
            return

        frames_sent = 0
        try:
            async for event in run_remote_streaming_v2(
                model,
                base_url=remote_url,
                simulation_time=simulation_time,
                time_step=time_step,
                snapshot_interval=snapshot_interval,
                animation_delay_ms=int(animation_delay * 1000),
            ):
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
                frames_sent += 1
                yield f"data: {payload}\n\n"
        except httpx.ConnectError as exc:
            if use_fallback:
                _log.warning(
                    "Simulation backend unreachable (%s), falling back to built-in engine", remote_url
                )
                yield f"data: {json.dumps({'warning': 'Remote backend unavailable, using built-in engine'})}\n\n"
                try:
                    async for chunk in _emit_events(_local_iter()):
                        yield chunk
                except Exception as fb_exc:
                    yield f"data: {_local_error_frame(fb_exc)}\n\n"
            else:
                message, kind = _simulation_error_message(exc, remote_url)
                yield f"data: {json.dumps({'error': message, 'kind': kind})}\n\n"
        except Exception as exc:
            if frames_sent > 0:
                _log.warning(
                    "Simulation backend (%s) disconnected after %d frames — cannot fall back mid-stream",
                    remote_url, frames_sent,
                )
                yield f"data: {json.dumps({'error': f'Remote backend disconnected after {frames_sent} frames', 'kind': 'transport'})}\n\n"
            else:
                message, kind = _simulation_error_message(exc, remote_url)
                yield f"data: {json.dumps({'error': message, 'kind': kind})}\n\n"
        yield _SSE_DONE

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _local_preview(model: ComposedModel) -> dict[str, Any]:
    """Validate *model* with no remote backend at all: export it to PNML
    with the SAME exporter `parse_composed_model_remote` would otherwise
    hand to petri-server, then round-trip that XML back through this
    application's own importer (services/petri/importer) instead of
    sending it anywhere. Used by preview_composed whenever
    SIMULATION_REMOTE_URL is unset, so a caller with no remote configured
    still gets real structural validation (every id, every page, every
    link resolved) rather than a flat refusal -- the response's own
    "validator" field says "local" so a caller can tell this apart from a
    real petri-server round trip, and the two are not silently conflated.

    Can raise ValueError exactly like `parse_composed_model_remote` does
    (the exporter's own `assert_invariants`) -- left to the caller's
    existing `except ValueError` handling rather than caught here, so both
    validators are reported through the one place that already turns that
    into a clean 400.
    """
    model_xml = get_composed_pnml_exporter().export(model)
    net_data, warnings = parse_pnml(model_xml)
    return {
        "validator": "local",
        "message": (
            "SIMULATION_REMOTE_URL is not configured; validated locally by "
            "round-tripping the exported PNML through this application's "
            "own importer instead of petri-server."
        ),
        "name": net_data.get("name"),
        "places": net_data.get("places", []),
        "transitions": net_data.get("transitions", []),
        "arcs": net_data.get("arcs", []),
        "objects": net_data.get("objects", []),
        "links": net_data.get("links", []),
        "warnings": warnings,
    }


@router.post(
    "/preview",
    summary="Export + parse a composed model, no simulation run",
    dependencies=[Depends(_simulate_rate_limit)],
)
async def preview_composed(
    body: ComposedSimulateBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> dict[str, Any]:
    """
    Cheap way to verify a composed model (including its links) before
    spending a full simulation run on it.

    With ``SIMULATION_REMOTE_URL`` configured, round-trips the generated
    PNML through petri-server's real ``POST /api/v2/model/parse``. With no
    remote configured, validates locally instead (see `_local_preview`):
    the exact same PNML this route would otherwise have sent to
    petri-server is round-tripped through this application's own importer.
    Either way the response states which validator ran (petri-server's own
    response shape for the remote path; a ``"validator": "local"`` field
    for the fallback).
    """
    model = await _resolve_composed_model(body, user, session)
    # Deliberately the raw URL, not simulation_remote_target: this endpoint
    # verifies a model AGAINST petri-server, so it is asking for that service
    # by name rather than for whichever engine happens to run simulations.
    remote_url = settings.SIMULATION_REMOTE_URL
    try:
        if not remote_url:
            return _local_preview(model)
        return await parse_composed_model_remote(model, remote_url)
    except json.JSONDecodeError as exc:
        # `resp.json()` inside `parse_composed_model_remote` raised: petri-server
        # answered 200 with a body that is not JSON (an HTML error page from a
        # proxy in front of it, a truncated response, ...). json.JSONDecodeError
        # is itself a ValueError subclass, so this branch has to come ahead of
        # the `except ValueError` below or it would be caught there instead and
        # mislabeled as the exporter rejecting the model, when the problem is
        # actually that the remote's response could not be understood at all.
        raise ServiceUnavailableException(
            f"Simulation backend returned an unreadable response ({remote_url})."
        ) from exc
    except ValueError as exc:
        # Raised by the exporter (`assert_invariants`) inside
        # `parse_composed_model_remote`, before any request reaches
        # petri-server: an invalid element id, a duplicate id, a cross-page
        # arc. Left uncaught this fell through every except clause below and
        # reached FastAPI's own unhandled-exception handler, which discards
        # the message and answers a bare 500 (exactly the "opaque failure"
        # this route exists to avoid on a model that is otherwise fine).
        raise BadRequestException(
            "Composed model cannot be exported to PNML",
            details=[{"field": "model", "message": str(exc)}],
        ) from exc
    except httpx.ConnectError as exc:
        raise ServiceUnavailableException(
            f"Simulation backend is unavailable ({remote_url}). Check that the service is running."
        ) from exc
    except httpx.TimeoutException as exc:
        raise ServiceUnavailableException(f"Simulation backend timed out ({remote_url}).") from exc
    except httpx.HTTPStatusError as exc:
        raise BadRequestException(
            f"Simulation backend rejected the model: HTTP {exc.response.status_code}."
        ) from exc
