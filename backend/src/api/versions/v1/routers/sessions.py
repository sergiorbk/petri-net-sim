"""Session management API endpoints - V1."""

import asyncio
import json
import logging
import uuid as _uuid
from typing import Any

import httpx

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.shared.exceptions import BadRequestException, NotFoundException
from src.api.shared.pnml_export import net_data_pnml_response
from src.api.shared.rate_limit import rate_limit
from src.api.shared.responses import ApiSuccessResponse
from src.api.shared.utils import success_response
from src.core.config import settings
from src.core.dependencies import get_current_user, get_postgres_session
from src.core.security_config import security_settings
from src.domain.models import PetriNet
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.net_snapshot_repository import NetSnapshotRepository
from src.infrastructure.postgres.repositories.session_repository import SessionRepository
from src.services.petri.session import is_composed_net_data
from src.services.simulation.engine import PetriSimulator
from src.services.simulation.limits import (
    clean_net_data as _clean_net_data,
    validate_simulation_request as _validate_simulation_request,
)
from src.services.simulation.remote import run_remote_streaming
from src.services.simulation.remote_error import remote_error_detail

_log = logging.getLogger(__name__)
_SSE_DONE = "data: [DONE]\n\n"

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Per-credential rate limit for the authenticated session simulate endpoints,
# sharing the same "simulate" budget/scope as the standalone /simulate route.
_simulate_rate_limit = rate_limit(
    scope="simulate",
    max_requests=security_settings.RATE_LIMIT_SIMULATE_MAX,
    window_seconds=security_settings.RATE_LIMIT_SIMULATE_WINDOW,
    by="token",
)

# The shared/public simulate endpoint has no credential, so it is keyed by
# client IP — it is the most exposed simulation entry point.
_shared_simulate_rate_limit = rate_limit(
    scope="simulate_shared",
    max_requests=security_settings.RATE_LIMIT_SIMULATE_MAX,
    window_seconds=security_settings.RATE_LIMIT_SIMULATE_WINDOW,
    by="ip",
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_VISIBILITY = {"private", "link_only", "public"}

#: Established clear-error text for a composed session hitting one of the
#: flat-net-only /simulate endpoints below. Constructing PetriNet(**net_data)
#: on composed net_data does not raise (pydantic v2's default is to ignore
#: the extra objectId/objects/links keys), so nothing here would 500 -- but
#: the result would be silently wrong instead: ids are only guaranteed
#: unique WITHIN one object (see composed_convert.py), so two objects that
#: legitimately share an id (e.g. both auto-numbered their first place "p1")
#: collide once flattened, and a transitionToPlace/placeFusion link carries
#: no local arc at all, so the transition or place it names would appear to
#: have no counterpart. Rejecting up front, before either failure mode can
#: happen, matches this file's own "No network to simulate" SSE-error
#: convention rather than letting a composed session run through an engine
#: that cannot represent it.
_COMPOSED_SESSION_REST_UNSUPPORTED = (
    "This session uses Petri-objects (a composed model). The session "
    "/simulate endpoints only run a single flat net. Use POST "
    "/api/v1/simulate/composed with this session's data, or simulate "
    "through the chat assistant or MCP tools, which support composed "
    "models directly."
)


def _composed_unsupported_response() -> StreamingResponse:
    """SSE-shaped rejection for the two streaming simulate endpoints, same
    terminal shape (one error frame then [DONE]) as the existing empty-net
    guard in _make_simulation_response."""
    async def _stream():
        yield f'data: {json.dumps({"error": _COMPOSED_SESSION_REST_UNSUPPORTED})}\n\n'
        yield _SSE_DONE

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _simulation_error_message(exc: Exception, remote_url: str | None) -> str:
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
        # falling through to the generic message below (mirrors how
        # simulate_composed.py's own _simulation_error_message treats a
        # ValueError as model, not transport, vocabulary).
        return str(exc)
    _log.exception("Simulation failed")
    return f"Simulation error: {exc}"


def _make_simulation_response(  # NOSONAR
    net_data: dict[str, Any],
    simulation_time: float,
    time_step: float,
    snapshot_interval: int | None,
    animation_delay: float,
) -> StreamingResponse:
    """Build a StreamingResponse for a simulation run. Shared by owner and public endpoints."""
    if is_composed_net_data(net_data):
        return _composed_unsupported_response()
    if not net_data.get("places"):
        async def _empty():
            yield 'data: {"error": "No network to simulate. Build a network first."}\n\n'
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
                yield f"data: {json.dumps({'warning': 'Remote backend unavailable, using built-in engine'})}\n\n"
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


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SessionListItem(BaseModel):
    """Session summary for list endpoint."""

    id: str = Field(description="Session ID (SHA-256 fingerprint)")
    title: str | None = Field(description="Session title")
    share_token: str = Field(description="Stable UUID used in share URLs")
    visibility: str = Field(description="private | link_only | public")
    created_at: str = Field(description="Creation timestamp")
    updated_at: str = Field(description="Last update timestamp")

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    """Paginated session list."""

    items: list[SessionListItem]
    has_more: bool


class SessionUpdateRequest(BaseModel):
    """Request to update session metadata."""

    title: str = Field(max_length=255, description="New session title")


class ShareRequest(BaseModel):
    """Request body for the share endpoint."""

    visibility: str = Field(description="private | link_only | public")


class ShareResponse(BaseModel):
    """Response from the share endpoint."""

    share_token: str = Field(description="Stable UUID token for the share URL")
    visibility: str = Field(description="Current visibility setting")


class SyncMessagesRequest(BaseModel):
    """Payload for syncing chat message history to the backend."""

    messages: list[dict[str, Any]]


class SessionMessagesResponse(BaseModel):
    """Stored chat message history for a session."""

    messages: list[dict[str, Any]]


class SharedSessionView(BaseModel):
    """Public read-only view of a shared session."""

    title: str | None
    share_token: str
    visibility: str
    net_data: dict
    messages: list[dict[str, Any]]
    created_at: str
    updated_at: str


class SimulateBody(BaseModel):
    """Optional body for the simulate endpoint.

    Resolution order:
    1. ``snapshot_id``  — fetch the specific versioned snapshot from DB (preferred).
    2. ``net_data``     — legacy fallback: full net JSON from the frontend
                          (used by old messages in localStorage that pre-date snapshots).
    3. Neither          — use the session's current ``net_data`` from the sessions table.
    """

    snapshot_id: _uuid.UUID | None = Field(
        default=None,
        description="UUID of a stored net snapshot. Takes precedence over net_data.",
    )
    net_data: dict[str, Any] | None = Field(
        default=None,
        description="Full Petri net JSON. Legacy fallback when snapshot_id is absent.",
    )


class NetSnapshotListItem(BaseModel):
    """Summary of a single net snapshot (no net_data — use the simulate endpoint)."""

    id: str = Field(description="Snapshot UUID")
    source: str = Field(description='"agent" or "user"')
    label: str | None = Field(description="User-assigned label, if any")
    created_at: str = Field(description="ISO-8601 creation timestamp")

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints — authenticated (owner)
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ApiSuccessResponse[SessionListResponse],
    summary="List user sessions",
)
async def list_sessions(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[SessionListResponse]:
    """List chat sessions for the authenticated user with cursor-style pagination."""
    repo = SessionRepository(session)
    sessions = await repo.list_by_user(user.id, limit=limit + 1, offset=offset)
    has_more = len(sessions) > limit
    items = [
        SessionListItem(
            id=s.id,
            title=s.title,
            share_token=str(s.share_token),
            visibility=s.visibility,
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )
        for s in sessions[:limit]
    ]
    return success_response(
        data=SessionListResponse(items=items, has_more=has_more), request=request
    )


@router.get(
    "/{session_id}/messages",
    response_model=ApiSuccessResponse[SessionMessagesResponse],
    summary="Get chat message history for a session",
)
async def get_session_messages(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[SessionMessagesResponse]:
    """Return the stored message history for a session.

    Returns an empty list when the session exists but no messages have been
    synced yet (new session or pre-014 row).
    """
    repo = SessionRepository(session)
    instance = await repo.get_by_id(session_id)

    if not instance or instance.user_id != user.id:
        raise NotFoundException(resource="Session", identifier=session_id)

    return success_response(
        data=SessionMessagesResponse(messages=instance.messages or []),
        request=request,
    )


@router.put(
    "/{session_id}/messages",
    response_model=ApiSuccessResponse[dict],
    summary="Sync chat message history for a session",
)
async def sync_session_messages(
    session_id: str,
    data: SyncMessagesRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[dict]:
    """Replace the stored message history for a session. Called by the frontend after each turn."""
    repo = SessionRepository(session)
    instance = await repo.get_by_id(session_id)

    if not instance or instance.user_id != user.id:
        raise NotFoundException(resource="Session", identifier=session_id)

    await repo.update_messages(session_id, data.messages)
    await session.commit()
    return success_response(data={"synced": True}, request=request)


@router.patch(
    "/{session_id}/share",
    response_model=ApiSuccessResponse[ShareResponse],
    summary="Update session sharing settings",
)
async def update_session_share(
    session_id: str,
    data: ShareRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[ShareResponse]:
    """Set visibility for a session. Returns the share token for building the share URL."""
    if data.visibility not in _VALID_VISIBILITY:
        raise BadRequestException("visibility must be one of: private, link_only, public")

    repo = SessionRepository(session)
    instance = await repo.get_by_id(session_id)

    if not instance or instance.user_id != user.id:
        raise NotFoundException(resource="Session", identifier=session_id)

    await repo.update_visibility(session_id, data.visibility)
    await session.commit()
    return success_response(
        data=ShareResponse(
            share_token=str(instance.share_token),
            visibility=data.visibility,
        ),
        request=request,
    )


@router.patch(
    "/{session_id}",
    response_model=ApiSuccessResponse[dict],
    summary="Update session",
)
async def update_session(
    session_id: str,
    data: SessionUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[dict]:
    """Update session title."""
    repo = SessionRepository(session)
    instance = await repo.get_by_id(session_id)

    if not instance or instance.user_id != user.id:
        raise NotFoundException(resource="Session", identifier=session_id)

    await repo.update_title(session_id, data.title)
    await session.commit()
    return success_response(data={"updated": True}, request=request)


@router.delete(
    "/{session_id}",
    response_model=ApiSuccessResponse[dict],
    summary="Delete session",
)
async def delete_session(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[dict]:
    """Delete a chat session."""
    repo = SessionRepository(session)
    deleted = await repo.delete_by_id(session_id, user.id)

    if not deleted:
        raise NotFoundException(resource="Session", identifier=session_id)

    await session.commit()
    return success_response(data={"deleted": True}, request=request)


@router.get(
    "/{session_id}/snapshots",
    response_model=ApiSuccessResponse[list[NetSnapshotListItem]],
    summary="List net snapshots for a session",
)
async def list_session_snapshots(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[list[NetSnapshotListItem]]:
    """Return all versioned net snapshots for a session, oldest first."""
    repo = SessionRepository(session)
    instance = await repo.get_by_id(session_id)

    if not instance or instance.user_id != user.id:
        raise NotFoundException(resource="Session", identifier=session_id)

    snapshot_repo = NetSnapshotRepository(session)
    snapshots = await snapshot_repo.list_by_session(session_id)
    items = [
        NetSnapshotListItem(
            id=str(s.id),
            source=s.source,
            label=s.label,
            created_at=s.created_at.isoformat(),
        )
        for s in snapshots
    ]
    return success_response(data=items, request=request)


@router.get(
    "/{session_id}/net",
    response_model=ApiSuccessResponse[dict],
    summary="Get session Petri net",
)
async def get_session_net(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[dict]:
    """Return the current Petri net structure for a session."""
    repo = SessionRepository(session)
    instance = await repo.get_by_id(session_id)

    if not instance or instance.user_id != user.id:
        raise NotFoundException(resource="Session", identifier=session_id)

    net_data = _clean_net_data(instance.net_data or {})
    return success_response(data=net_data, request=request)


@router.get(
    "/{session_id}/pnml",
    summary="Export a session's Petri net as PNML",
)
async def get_session_pnml(
    session_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> Response:
    """Export the session's current model as a downloadable PNML XML file.

    Composed dialect (one page per Petri-object, plus the free pool) is
    used automatically when the session has any object or link -- the
    same dialect selection PetriNetSession.export_pnml already applies
    everywhere else (agent tools, chat, MCP). A flat session gets the
    single flat dialect.
    """
    repo = SessionRepository(session)
    instance = await repo.get_by_id(session_id)

    if not instance or instance.user_id != user.id:
        raise NotFoundException(resource="Session", identifier=session_id)

    net_data = _clean_net_data(instance.net_data or {})
    return net_data_pnml_response(net_data, instance.title or session_id)


@router.post(
    "/{session_id}/simulate",
    summary="Stream a simulation for the session Petri net",
    dependencies=[Depends(_simulate_rate_limit)],
)
async def simulate_session(
    session_id: str,
    simulation_time: float = Query(default=3600.0, gt=0, description="Simulation time units"),
    time_step: float = Query(
        default=1.0,
        gt=0,
        description=(
            "Time-based mode: emit a snapshot every this many simulation time units. "
            "Total snapshots ≈ simulation_time / time_step. "
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
        description=(
            "Real-time pause (seconds) inserted after each snapshot. "
            "0 = stream as fast as possible (scientific / batch use)."
        ),
    ),
    body: SimulateBody = Body(default_factory=SimulateBody),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> StreamingResponse:
    """
    Stream a discrete-event simulation for the session's Petri net.

    Returns ``text/event-stream`` chunks terminated by ``data: [DONE]``.

    **Two snapshot modes**

    * **Time-based** (default): one snapshot every ``time_step`` simulation units.
    * **Step-based** (scientific): one snapshot every ``snapshot_interval`` transition firings.
    """
    repo = SessionRepository(session)
    snapshot_repo = NetSnapshotRepository(session)
    instance = await repo.get_by_id(session_id)
    session_accessible = instance is not None and instance.user_id == user.id

    if body.snapshot_id:
        snap = await snapshot_repo.get_by_id_and_session(body.snapshot_id, session_id)
        if not snap:
            raise NotFoundException(resource="Snapshot", identifier=str(body.snapshot_id))
        net_data = _clean_net_data(snap.net_data)
    elif not session_accessible:
        if not body.net_data:
            raise NotFoundException(resource="Session", identifier=session_id)
        net_data = _clean_net_data(body.net_data)
    elif body.net_data:
        net_data = _clean_net_data(body.net_data)
    else:
        net_data = _clean_net_data(instance.net_data or {})

    _validate_simulation_request(net_data, simulation_time)

    return _make_simulation_response(net_data, simulation_time, time_step, snapshot_interval, animation_delay)


@router.post(
    "/{session_id}/simulate/precompute",
    summary="Pre-run session simulation, return all snapshots as JSON",
    dependencies=[Depends(_simulate_rate_limit)],
)
async def simulate_session_precompute(  # NOSONAR
    session_id: str,
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
    body: SimulateBody = Body(default_factory=SimulateBody),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> dict[str, Any]:
    """Run the full simulation synchronously and return all snapshots as a JSON array."""
    repo = SessionRepository(session)
    snapshot_repo = NetSnapshotRepository(session)
    instance = await repo.get_by_id(session_id)
    session_accessible = instance is not None and instance.user_id == user.id

    if body.snapshot_id:
        snap = await snapshot_repo.get_by_id_and_session(body.snapshot_id, session_id)
        if not snap:
            raise NotFoundException(resource="Snapshot", identifier=str(body.snapshot_id))
        net_data = _clean_net_data(snap.net_data)
    elif not session_accessible:
        if not body.net_data:
            raise NotFoundException(resource="Session", identifier=session_id)
        net_data = _clean_net_data(body.net_data)
    elif body.net_data:
        net_data = _clean_net_data(body.net_data)
    else:
        net_data = _clean_net_data(instance.net_data or {})

    _validate_simulation_request(net_data, simulation_time)

    if is_composed_net_data(net_data):
        raise HTTPException(status_code=422, detail=_COMPOSED_SESSION_REST_UNSUPPORTED)

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
        # In-loop engine caps (step / wall-clock) surface as RuntimeError.
        raise HTTPException(status_code=422, detail=str(exc))

    return {"snapshots": snapshots, "total": len(snapshots), "truncated": truncated}


# ---------------------------------------------------------------------------
# Endpoints — public (no authentication required)
# ---------------------------------------------------------------------------

@router.get(
    "/shared/{share_token}",
    response_model=ApiSuccessResponse[SharedSessionView],
    summary="Get a shared session by share token",
)
async def get_shared_session(
    share_token: _uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[SharedSessionView]:
    """
    Public read-only view of a session via its share token.

    Returns 404 when the token is unknown or the session is private.
    No authentication required for link_only and public sessions.
    """
    repo = SessionRepository(session)
    instance = await repo.get_by_share_token(share_token)

    if not instance or instance.visibility == "private":
        raise NotFoundException(resource="SharedSession", identifier=str(share_token))

    return success_response(
        data=SharedSessionView(
            title=instance.title,
            share_token=str(instance.share_token),
            visibility=instance.visibility,
            net_data=_clean_net_data(instance.net_data or {}),
            messages=instance.messages or [],
            created_at=instance.created_at.isoformat(),
            updated_at=instance.updated_at.isoformat(),
        ),
        request=request,
    )


@router.get(
    "/shared/{share_token}/snapshots",
    response_model=ApiSuccessResponse[list[NetSnapshotListItem]],
    summary="List net snapshots for a shared session",
)
async def list_shared_session_snapshots(
    share_token: _uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[list[NetSnapshotListItem]]:
    """Return all versioned net snapshots for a shared session. No authentication required."""
    repo = SessionRepository(session)
    instance = await repo.get_by_share_token(share_token)

    if not instance or instance.visibility == "private":
        raise NotFoundException(resource="SharedSession", identifier=str(share_token))

    snapshot_repo = NetSnapshotRepository(session)
    snapshots = await snapshot_repo.list_by_session(instance.id)
    items = [
        NetSnapshotListItem(
            id=str(s.id),
            source=s.source,
            label=s.label,
            created_at=s.created_at.isoformat(),
        )
        for s in snapshots
    ]
    return success_response(data=items, request=request)


@router.get(
    "/shared/{share_token}/snapshots/{snapshot_id}",
    response_model=ApiSuccessResponse[dict],
    summary="Get net_data for a specific snapshot of a shared session",
)
async def get_shared_snapshot_net(
    share_token: _uuid.UUID,
    snapshot_id: _uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
) -> ApiSuccessResponse[dict]:
    """Return net_data for a specific snapshot. No authentication required for shared sessions."""
    repo = SessionRepository(session)
    instance = await repo.get_by_share_token(share_token)

    if not instance or instance.visibility == "private":
        raise NotFoundException(resource="SharedSession", identifier=str(share_token))

    snapshot_repo = NetSnapshotRepository(session)
    snap = await snapshot_repo.get_by_id_and_session(snapshot_id, instance.id)

    if not snap:
        raise NotFoundException(resource="Snapshot", identifier=str(snapshot_id))

    return success_response(data=_clean_net_data(snap.net_data), request=request)


@router.post(
    "/shared/{share_token}/simulate",
    summary="Stream a simulation for a shared session",
    dependencies=[Depends(_shared_simulate_rate_limit)],
)
async def simulate_shared_session(
    share_token: _uuid.UUID,
    simulation_time: float = Query(default=3600.0, gt=0),
    time_step: float = Query(default=1.0, gt=0),
    snapshot_interval: int | None = Query(default=None, ge=1),
    animation_delay: float = Query(default=0.0, ge=0.0, le=10.0),
    body: SimulateBody = Body(default_factory=SimulateBody),
    session: AsyncSession = Depends(get_postgres_session),
) -> StreamingResponse:
    """
    Stream a simulation for a publicly shared session.

    No authentication required for link_only and public sessions.
    Resolution order for net: snapshot_id > session's current net_data.
    """
    repo = SessionRepository(session)
    instance = await repo.get_by_share_token(share_token)

    if not instance or instance.visibility == "private":
        raise NotFoundException(resource="SharedSession", identifier=str(share_token))

    snapshot_repo = NetSnapshotRepository(session)

    if body.snapshot_id:
        snap = await snapshot_repo.get_by_id_and_session(body.snapshot_id, instance.id)
        if not snap:
            raise NotFoundException(resource="Snapshot", identifier=str(body.snapshot_id))
        net_data = _clean_net_data(snap.net_data)
    else:
        net_data = _clean_net_data(instance.net_data or {})

    _validate_simulation_request(net_data, simulation_time)

    return _make_simulation_response(net_data, simulation_time, time_step, snapshot_interval, animation_delay)


class TrainingExportRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    conversation: list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] | None = None


@router.post("/{session_id}/training-data", summary="Download task-scoped training data")
async def export_session_training_data(
    session_id: str,
    body: TrainingExportRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> Response:
    from src.services.training_export import build_training_bundle, attachment
    from starlette.concurrency import run_in_threadpool
    instance = await SessionRepository(session).get_by_id(session_id)
    if not instance or instance.user_id != user.id:
        raise NotFoundException(resource="Session", identifier=session_id)
    messages = body.conversation
    origin = "client-provided" if messages is not None else "application"
    if messages is None:
        messages = [{"role": row["role"], "content": row.get("content", "")}
                    for row in (instance.messages or []) if row.get("role") in {"user", "assistant"}]
    try:
        data, name = await run_in_threadpool(
            build_training_bundle, instance.net_data or {}, instance.title or "Petri session",
            context=body.context, conversation=messages, tool_calls=body.tool_calls,
            conversation_origin=origin, tool_origin="client-provided" if body.tool_calls else "unavailable",
        )
    except ValueError as exc:
        raise BadRequestException("Invalid training export data") from exc
    return attachment(data, name, "application/zip")


class NetworkImageRequest(BaseModel):
    net_data: dict[str, Any]
    title: str = "Petri network"


@router.post("/exports/image", summary="Render current editor model as PNG")
async def export_network_image(body: NetworkImageRequest, user: User = Depends(get_current_user)) -> Response:
    from src.services.training_export import render_network, attachment, filename
    from starlette.concurrency import run_in_threadpool
    try:
        data, _ = await run_in_threadpool(render_network, body.net_data)
    except (ValueError, KeyError, TypeError) as exc:
        raise BadRequestException("Invalid network image data") from exc
    return attachment(data, filename(body.title, ".png"), "image/png")
