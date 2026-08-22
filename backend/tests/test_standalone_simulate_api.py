"""Tests for /v1/simulate and /v1/simulate/precompute standalone endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.services.petri.session import PetriNetSession


def _make_mm1_net_data() -> dict:
    s = PetriNetSession()
    s.create_network("MM1")
    gen = s.builder.add_generator("Gen1", interval=5.0)
    machine = s.builder.add_machine("Server", processing_time=2.0)
    term = s.builder.add_terminator("Exit")
    s.builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
    s.builder.connect(machine.interface.output_place_id, term.interface.input_place_id)
    data = s.to_net_data()
    data.pop("_last_output_place_id", None)
    data.pop("_has_custom_topology", None)
    return data


def _create_test_app() -> FastAPI:
    from src.api.shared.exceptions import ApiException
    from src.api.shared.handlers import api_exception_handler
    from src.api.versions.v1.routers.auth import router as auth_router
    from src.api.versions.v1.routers.simulate import router as simulate_router

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.add_exception_handler(ApiException, api_exception_handler)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(simulate_router, prefix="/api/v1")
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


# ---------------------------------------------------------------------------
# POST /simulate — streaming SSE
# ---------------------------------------------------------------------------


class TestStandaloneSimulate:
    def test_simulate_valid_net_returns_200(self, client):
        token = _signup(client, "sa1@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/simulate?simulation_time=15&time_step=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert "[DONE]" in resp.text

    def test_simulate_empty_net_returns_error_event(self, client):
        token = _signup(client, "sa2@example.com")

        resp = client.post(
            "/api/v1/simulate?simulation_time=10",
            json={"net_data": {"places": []}},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        body = resp.text
        assert "error" in body.lower() or "[DONE]" in body

    def test_simulate_step_based_mode(self, client):
        token = _signup(client, "sa3@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/simulate?simulation_time=20&snapshot_interval=3",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert "[DONE]" in resp.text

    def test_simulate_strips_internal_keys(self, client):
        token = _signup(client, "sa4@example.com")
        net_data = _make_mm1_net_data()
        net_data["_last_pnml_export"] = "should_be_ignored"

        resp = client.post(
            "/api/v1/simulate?simulation_time=10&time_step=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert "[DONE]" in resp.text

    def test_simulate_requires_auth(self, client):
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/simulate?simulation_time=10",
            json={"net_data": net_data},
        )

        assert resp.status_code == 401

    def test_simulate_returns_sse_content_type(self, client):
        token = _signup(client, "sa5@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/simulate?simulation_time=10&time_step=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# POST /simulate/precompute
# ---------------------------------------------------------------------------


class TestStandalonePrecompute:
    def test_precompute_valid_net(self, client):
        token = _signup(client, "sp1@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/simulate/precompute?simulation_time=20&time_step=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "snapshots" in data
        assert "total" in data
        assert isinstance(data["snapshots"], list)
        assert data["total"] == len(data["snapshots"])

    def test_precompute_empty_net_returns_empty(self, client):
        token = _signup(client, "sp2@example.com")

        resp = client.post(
            "/api/v1/simulate/precompute?simulation_time=10",
            json={"net_data": {"places": []}},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshots"] == []
        assert data["total"] == 0

    def test_precompute_expand_phases(self, client):
        token = _signup(client, "sp3@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/simulate/precompute?simulation_time=20&snapshot_interval=3&expand_phases=true",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["snapshots"], list)

    def test_precompute_snapshot_interval_mode(self, client):
        token = _signup(client, "sp4@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/simulate/precompute?simulation_time=20&snapshot_interval=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "snapshots" in data

    def test_precompute_strips_internal_keys(self, client):
        token = _signup(client, "sp5@example.com")
        net_data = _make_mm1_net_data()
        net_data["_last_output_place_id"] = "garbage"

        resp = client.post(
            "/api/v1/simulate/precompute?simulation_time=15&time_step=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200

    def test_precompute_requires_auth(self, client):
        resp = client.post(
            "/api/v1/simulate/precompute?simulation_time=10",
            json={"net_data": {"places": []}},
        )
        assert resp.status_code == 401

    def test_precompute_snapshot_contains_expected_fields(self, client):
        token = _signup(client, "sp6@example.com")
        net_data = _make_mm1_net_data()

        resp = client.post(
            "/api/v1/simulate/precompute?simulation_time=20&time_step=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        if data["snapshots"]:
            snap = data["snapshots"][0]
            assert "markings" in snap
            assert "buffers" in snap
            assert "current_time" in snap
            assert "step_number" in snap


class TestSimulationErrorMessageBodyExtraction:
    """simulate.py's `_simulation_error_message` adopts the same petri-server
    error-body extraction as simulate_composed.py's, instead of collapsing
    every 4xx to a bare "HTTP {status}." (see remote_error.py)."""

    def _status_error(self, status: int, body: str, content_type: str = "application/json"):
        import httpx

        request = httpx.Request("POST", "http://petri-server:8080/v1/simulate")
        response = httpx.Response(
            status, content=body.encode(), headers={"content-type": content_type}, request=request
        )
        return httpx.HTTPStatusError("boom", request=request, response=response)

    def test_4xx_json_message_body_is_surfaced(self):
        from src.api.versions.v1.routers.simulate import _simulation_error_message

        exc = self._status_error(400, '{"message": "transition T1 has no input places"}')
        message = _simulation_error_message(exc, "http://petri-server:8080")
        assert message == "transition T1 has no input places"

    def test_5xx_falls_back_to_generic_status_message(self):
        from src.api.versions.v1.routers.simulate import _simulation_error_message

        exc = self._status_error(500, "boom")
        message = _simulation_error_message(exc, "http://petri-server:8080")
        assert message == "Simulation backend returned an error: HTTP 500."

    def test_value_error_is_surfaced_verbatim_not_as_generic_internal_error(self):
        """A ValueError raised by the exporter's own invariant checks (an
        invalid element id, a duplicate id, a cross-page arc) happens before
        any request reaches a remote backend. It used to have no dedicated
        branch here and fell all the way through to the generic "Simulation
        failed due to an internal error." message, hiding the one sentence
        the user could act on."""
        from src.api.versions.v1.routers.simulate import _simulation_error_message

        exc = ValueError("'p1\\n' is not a valid XML NCName")
        message = _simulation_error_message(exc, "http://petri-server:8080")
        assert message == "'p1\\n' is not a valid XML NCName"
