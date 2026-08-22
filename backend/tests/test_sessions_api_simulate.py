"""Tests for /v1/sessions/{id}/simulate and /simulate/precompute endpoints."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.net_snapshot import NetSnapshot
from src.infrastructure.postgres.models.session import Session as SessionModel
from src.infrastructure.postgres.models.user import User
from src.services.petri.session import PetriNetSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sid() -> str:
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()


def _make_mm1_net_data() -> dict:
    """Build a minimal valid Petri net dict suitable for simulation."""
    s = PetriNetSession()
    s.create_network("MM1")
    gen = s.builder.add_generator("Gen1", interval=5.0)
    machine = s.builder.add_machine("Server", processing_time=2.0)
    term = s.builder.add_terminator("Exit")
    s.builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
    s.builder.connect(machine.interface.output_place_id, term.interface.input_place_id)
    data = s.to_net_data()
    # Strip session-internal keys so it matches what the API accepts
    data.pop("_last_output_place_id", None)
    data.pop("_has_custom_topology", None)
    return data


def _create_test_app() -> FastAPI:
    from src.api.shared.exceptions import ApiException
    from src.api.shared.handlers import api_exception_handler
    from src.api.versions.v1.routers.auth import router as auth_router
    from src.api.versions.v1.routers.sessions import router as sessions_router

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.add_exception_handler(ApiException, api_exception_handler)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    return app


@pytest.fixture
def app():
    return _create_test_app()


@pytest.fixture
def client(app, session_factory):
    from src.core.dependencies import get_postgres_session

    async def _override_session():
        async with session_factory() as sess:
            yield sess

    app.dependency_overrides[get_postgres_session] = _override_session
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _signup(client: TestClient, email: str = "sim@example.com") -> str:
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_db_session(
    db: AsyncSession,
    user: User,
    net_data: dict | None = None,
    session_id: str | None = None,
) -> SessionModel:
    s = SessionModel(
        id=session_id or _sid(),
        user_id=user.id,
        net_data=net_data or {},
        messages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_accessed_at=datetime.now(UTC),
    )
    db.add(s)
    await db.flush()
    await db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# POST /sessions/{id}/simulate (streaming SSE)
# ---------------------------------------------------------------------------


class TestSimulateSession:
    def test_simulate_with_inline_net_data(self, client):
        """Pass net_data in body — no DB session needed."""
        token = _signup(client, "sim1@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/sessions/dummy_session/simulate?simulation_time=10&time_step=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        # SSE streams — TestClient collects the full body
        assert resp.status_code == 200
        body = resp.text
        assert "[DONE]" in body

    def test_simulate_empty_net_returns_error_event(self, client):
        token = _signup(client, "sim2@example.com")

        resp = client.post(
            "/api/v1/sessions/dummy/simulate?simulation_time=10",
            json={"net_data": {"places": []}},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        body = resp.text
        assert "error" in body.lower() or "[DONE]" in body

    @pytest.mark.anyio
    async def test_simulate_uses_session_net_data(self, client, session, password_user):
        net_data = _make_mm1_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        resp = client.post(
            f"/api/v1/sessions/{s.id}/simulate?simulation_time=10&time_step=5",
            json={},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert "[DONE]" in resp.text

    @pytest.mark.anyio
    async def test_simulate_with_snapshot_id(self, client, session, password_user):
        net_data = _make_mm1_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        snap = NetSnapshot(
            session_id=s.id,
            net_data=net_data,
            content_hash=hashlib.sha256(
                json.dumps(net_data, sort_keys=True).encode()
            ).hexdigest(),
            source="agent",
        )
        session.add(snap)
        await session.commit()
        await session.refresh(snap)

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        resp = client.post(
            f"/api/v1/sessions/{s.id}/simulate?simulation_time=10",
            json={"snapshot_id": str(snap.id)},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert "[DONE]" in resp.text

    @pytest.mark.anyio
    async def test_simulate_nonexistent_snapshot_returns_404(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        resp = client.post(
            f"/api/v1/sessions/{s.id}/simulate?simulation_time=10",
            json={"snapshot_id": str(uuid.uuid4())},
            headers=_auth(token),
        )

        assert resp.status_code == 404

    def test_simulate_step_based_mode(self, client):
        """snapshot_interval parameter triggers step-based mode."""
        token = _signup(client, "sim3@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/sessions/dummy/simulate?simulation_time=20&snapshot_interval=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert "[DONE]" in resp.text


# ---------------------------------------------------------------------------
# POST /sessions/{id}/simulate/precompute
# ---------------------------------------------------------------------------


class TestSimulatePrecompute:
    def test_precompute_with_inline_net_data(self, client):
        token = _signup(client, "pre1@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/sessions/dummy/simulate/precompute?simulation_time=20&time_step=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "snapshots" in data
        assert "total" in data
        assert isinstance(data["snapshots"], list)

    def test_precompute_empty_net_returns_empty(self, client):
        token = _signup(client, "pre2@example.com")

        resp = client.post(
            "/api/v1/sessions/dummy/simulate/precompute?simulation_time=10",
            json={"net_data": {"places": []}},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshots"] == []
        assert data["total"] == 0

    @pytest.mark.anyio
    async def test_precompute_uses_session_net(self, client, session, password_user):
        net_data = _make_mm1_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        resp = client.post(
            f"/api/v1/sessions/{s.id}/simulate/precompute?simulation_time=20&time_step=5",
            json={},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["total"] >= 0

    def test_precompute_expand_phases(self, client):
        token = _signup(client, "pre3@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/sessions/dummy/simulate/precompute?simulation_time=20&snapshot_interval=3&expand_phases=true",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["snapshots"], list)

    def test_precompute_snapshot_interval_mode(self, client):
        token = _signup(client, "pre4@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/sessions/dummy/simulate/precompute?simulation_time=20&snapshot_interval=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "snapshots" in data

    @pytest.mark.anyio
    async def test_precompute_with_snapshot_id(self, client, session, password_user):
        net_data = _make_mm1_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        snap = NetSnapshot(
            session_id=s.id,
            net_data=net_data,
            content_hash=hashlib.sha256(
                json.dumps(net_data, sort_keys=True).encode()
            ).hexdigest(),
            source="agent",
        )
        session.add(snap)
        await session.commit()
        await session.refresh(snap)

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        resp = client.post(
            f"/api/v1/sessions/{s.id}/simulate/precompute?simulation_time=20&time_step=5",
            json={"snapshot_id": str(snap.id)},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["total"] >= 0

    @pytest.mark.anyio
    async def test_precompute_nonexistent_snapshot_returns_404(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        resp = client.post(
            f"/api/v1/sessions/{s.id}/simulate/precompute?simulation_time=10",
            json={"snapshot_id": str(uuid.uuid4())},
            headers=_auth(token),
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Public shared session simulate
# ---------------------------------------------------------------------------


class TestSharedSimulate:
    @pytest.mark.anyio
    async def test_shared_simulate_link_only(self, client, session, password_user):
        net_data = _make_mm1_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        s.visibility = "link_only"
        await session.flush()
        await session.commit()

        resp = client.post(
            f"/api/v1/sessions/shared/{s.share_token}/simulate?simulation_time=10",
            json={},
        )

        assert resp.status_code == 200
        assert "[DONE]" in resp.text

    @pytest.mark.anyio
    async def test_shared_simulate_private_returns_404(self, client, session, password_user):
        s = await _create_db_session(session, password_user)
        s.visibility = "private"
        await session.flush()
        await session.commit()

        resp = client.post(
            f"/api/v1/sessions/shared/{s.share_token}/simulate?simulation_time=10",
            json={},
        )

        assert resp.status_code == 404

    def test_shared_simulate_unknown_token_returns_404(self, client):
        resp = client.post(
            f"/api/v1/sessions/shared/{uuid.uuid4()}/simulate?simulation_time=10",
            json={},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Simulation safety caps
# ---------------------------------------------------------------------------


def _oversized_net_data() -> dict:
    """A net whose place count exceeds SIMULATION_MAX_PLACES."""
    from src.core.security_config import security_settings

    n = security_settings.SIMULATION_MAX_PLACES + 1
    return {
        "places": [{"id": f"p{i}", "name": f"p{i}", "tokens": 0} for i in range(n)],
        "transitions": [],
        "arcs": [],
    }


class TestSimulationCapsOnSessionEndpoints:
    def test_simulate_rejects_oversized_net(self, client):
        token = _signup(client, "cap1@example.com")
        resp = client.post(
            "/api/v1/sessions/dummy/simulate?simulation_time=10",
            json={"net_data": _oversized_net_data()},
            headers=_auth(token),
        )
        assert resp.status_code == 422
        assert "safety limits" in resp.text.lower()

    def test_simulate_rejects_excessive_simulation_time(self, client):
        from src.core.security_config import security_settings

        token = _signup(client, "cap2@example.com")
        too_long = security_settings.SIMULATION_MAX_TIME + 1
        resp = client.post(
            f"/api/v1/sessions/dummy/simulate?simulation_time={too_long}",
            json={"net_data": _make_mm1_net_data()},
            headers=_auth(token),
        )
        assert resp.status_code == 422
        assert "simulation_time" in resp.text

    def test_precompute_rejects_oversized_net(self, client):
        token = _signup(client, "cap3@example.com")
        resp = client.post(
            "/api/v1/sessions/dummy/simulate/precompute?simulation_time=10",
            json={"net_data": _oversized_net_data()},
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_precompute_response_has_truncated_flag(self, client):
        token = _signup(client, "cap4@example.com")
        resp = client.post(
            "/api/v1/sessions/dummy/simulate/precompute?simulation_time=20&time_step=5",
            json={"net_data": _make_mm1_net_data()},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert "truncated" in resp.json()

    @pytest.mark.anyio
    async def test_shared_simulate_rejects_oversized_net(self, client, session, password_user):
        s = await _create_db_session(session, password_user, net_data=_oversized_net_data())
        s.visibility = "link_only"
        await session.flush()
        await session.commit()

        resp = client.post(
            f"/api/v1/sessions/shared/{s.share_token}/simulate?simulation_time=10",
            json={},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Rate limiting wired onto session simulate endpoints
# ---------------------------------------------------------------------------


class TestSimulateRateLimit:
    @pytest.mark.anyio
    async def test_simulate_returns_429_when_limit_exceeded(
        self, client, session, password_user, monkeypatch
    ):
        s = await _create_db_session(session, password_user, net_data=_make_mm1_net_data())
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        # Patch only after auth is set up, so the forced over-limit applies to the
        # simulate call rather than to signup.
        async def over_limit(key, max_requests, window):
            return False, max_requests + 1, 30

        monkeypatch.setattr("src.api.shared.rate_limit._hit", over_limit)

        resp = client.post(
            f"/api/v1/sessions/{s.id}/simulate?simulation_time=10",
            json={},
            headers=_auth(token),
        )
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "30"

    @pytest.mark.anyio
    async def test_precompute_returns_429_when_limit_exceeded(
        self, client, session, password_user, monkeypatch
    ):
        s = await _create_db_session(session, password_user, net_data=_make_mm1_net_data())
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        async def over_limit(key, max_requests, window):
            return False, max_requests + 1, 30

        monkeypatch.setattr("src.api.shared.rate_limit._hit", over_limit)

        resp = client.post(
            f"/api/v1/sessions/{s.id}/simulate/precompute?simulation_time=10",
            json={},
            headers=_auth(token),
        )
        assert resp.status_code == 429

    @pytest.mark.anyio
    async def test_shared_simulate_returns_429_when_limit_exceeded(
        self, client, session, password_user, monkeypatch
    ):
        s = await _create_db_session(session, password_user, net_data=_make_mm1_net_data())
        s.visibility = "link_only"
        await session.flush()
        await session.commit()

        async def over_limit(key, max_requests, window):
            return False, max_requests + 1, 30

        monkeypatch.setattr("src.api.shared.rate_limit._hit", over_limit)

        resp = client.post(
            f"/api/v1/sessions/shared/{s.share_token}/simulate?simulation_time=10",
            json={},
        )
        assert resp.status_code == 429


class TestSimulationErrorMessageBodyExtraction:
    """sessions.py's `_simulation_error_message` adopts the same
    petri-server error-body extraction as simulate_composed.py's, instead of
    collapsing every 4xx to a bare "HTTP {status}." (see remote_error.py)."""

    def _status_error(self, status: int, body: str, content_type: str = "application/json"):
        import httpx

        request = httpx.Request("POST", "http://petri-server:8080/v1/simulate")
        response = httpx.Response(
            status, content=body.encode(), headers={"content-type": content_type}, request=request
        )
        return httpx.HTTPStatusError("boom", request=request, response=response)

    def test_4xx_json_message_body_is_surfaced(self):
        from src.api.versions.v1.routers.sessions import _simulation_error_message

        exc = self._status_error(400, '{"message": "transition T1 has no input places"}')
        message = _simulation_error_message(exc, "http://petri-server:8080")
        assert message == "transition T1 has no input places"

    def test_5xx_falls_back_to_generic_status_message(self):
        from src.api.versions.v1.routers.sessions import _simulation_error_message

        exc = self._status_error(500, "boom")
        message = _simulation_error_message(exc, "http://petri-server:8080")
        assert message == "Simulation backend returned an error: HTTP 500."

    def test_value_error_is_surfaced_verbatim_not_as_generic_internal_error(self):
        """A ValueError raised by the exporter's own invariant checks (an
        invalid element id, a duplicate id, a cross-page arc) happens before
        any request reaches a remote backend. It used to have no dedicated
        branch here and fell all the way through to the generic
        "Simulation error: ..." fallback that also logs a full traceback for
        what is really a problem with the model, not the deployment."""
        from src.api.versions.v1.routers.sessions import _simulation_error_message

        exc = ValueError("'p1\\n' is not a valid XML NCName")
        message = _simulation_error_message(exc, "http://petri-server:8080")
        assert message == "'p1\\n' is not a valid XML NCName"
