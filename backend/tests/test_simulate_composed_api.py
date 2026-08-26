"""Tests for /v1/simulate/composed and /v1/simulate/composed/preview.

Focused on the safety-cap and validation fixes found by review: unlike the
flat-net endpoints, this router had no resource caps, no rate limit on
/preview, and no bounds validation on link indices before this file's
companion fixes landed. Each test below pins down one of those behaviors.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_single_place_net_data() -> dict:
    """Minimal valid net_data: one place, no transitions.

    ComposedModel.validate()'s only structural requirement is "every
    transition has a local input arc" — a net with zero transitions
    trivially satisfies that, so this is the cheapest valid composed-object
    body for tests that don't care about the net's own shape.
    """
    return {
        "places": [{"id": "p1", "name": "p1", "tokens": 0, "graphics": {"x": 0, "y": 0}}],
        "transitions": [],
        "arcs": [],
    }


def _create_test_app() -> FastAPI:
    from src.api.shared.exceptions import ApiException
    from src.api.shared.handlers import api_exception_handler
    from src.api.versions.v1.routers.auth import router as auth_router
    from src.api.versions.v1.routers.simulate_composed import router as composed_router

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.add_exception_handler(ApiException, api_exception_handler)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(composed_router, prefix="/api/v1")
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


def _signup(client: TestClient, email: str = "composed@example.com") -> str:
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestComposedResourceCaps:
    def test_preview_rejects_more_objects_than_max(self, client):
        token = _signup(client, "cap1@example.com")
        from src.core.security_config import security_settings

        too_many = [{} for _ in range(security_settings.SIMULATION_MAX_OBJECTS + 1)]

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={"objects": too_many},
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_preview_rejects_oversized_object_net(self, client, monkeypatch):
        token = _signup(client, "cap2@example.com")
        monkeypatch.setattr(
            "src.core.security_config.security_settings.SIMULATION_MAX_PLACES", 1
        )
        net_data = _make_mm1_net_data()
        assert len(net_data["places"]) > 1  # sanity: the cap is actually exceeded

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={"objects": [{"net_data": net_data}]},
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_simulate_composed_rejects_simulation_time_over_max(self, client):
        token = _signup(client, "cap3@example.com")
        net_data = _make_single_place_net_data()

        resp = client.post(
            "/api/v1/simulate/composed?simulation_time=999999999999",
            json={"objects": [{"net_data": net_data}]},
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_valid_small_model_passes_all_caps_and_validates_locally(self, client, monkeypatch):
        """A well-formed, small request should clear every cap and validate
        successfully through the local fallback, not be rejected.

        With no remote backend configured, /preview no longer refuses
        outright: it round-trips the exported PNML through this
        application's own importer instead (see
        simulate_composed._local_preview) and reports the same structure
        back, tagged with which validator actually ran.

        Explicitly forces SIMULATION_REMOTE_URL unset regardless of the host's
        ambient environment (e.g. a leftover .env from manual Docker testing)
        so this test's outcome doesn't depend on machine-local state.
        """
        monkeypatch.setattr("src.core.config.settings.SIMULATION_REMOTE_URL", None)
        token = _signup(client, "cap4@example.com")
        net_data = _make_single_place_net_data()

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={"objects": [{"net_data": net_data}]},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["validator"] == "local"
        assert "SIMULATION_REMOTE_URL" in data["message"]
        assert [p["id"] for p in data["places"]] == ["p1"]

    def test_preview_reports_unreachable_backend_cleanly_not_as_a_500(
        self, client, monkeypatch
    ):
        """A configured-but-unreachable remote must surface as a clean 503,
        matching the streaming endpoint's behavior — not an unhandled 500."""
        monkeypatch.setattr(
            "src.core.config.settings.SIMULATION_REMOTE_URL", "http://127.0.0.1:1"
        )
        token = _signup(client, "cap5@example.com")
        net_data = _make_single_place_net_data()

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={"objects": [{"net_data": net_data}]},
            headers=_auth(token),
        )
        assert resp.status_code == 503


class TestComposedObjectNetValidation:
    def test_a_net_the_domain_model_refuses_is_a_400_not_a_500(self, client):
        """A distribution the engine cannot run with is this request's problem.
        It used to escape as an unhandled error, so the canvas reported that the
        simulation service was unavailable and hid the one sentence the user
        could act on."""
        token = _signup(client, "objnet1@example.com")
        net_data = _make_single_place_net_data()
        net_data["transitions"] = [
            {
                "id": "t1",
                "name": "T1",
                "priority": 1,
                "distribution": "norm",
                "mean_delay": 3.0,
                "standard_deviation": 0.0,
                "probability": None,
                "graphics": {"x": 0, "y": 0},
            }
        ]

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={"objects": [{"name": "Middle", "net_data": net_data}]},
            headers=_auth(token),
        )

        assert resp.status_code == 400
        message = resp.json()["error"]["message"]
        assert "Middle" in message
        assert "standard_deviation" in message


class TestComposedLinkBoundsValidation:
    def test_negative_link_index_returns_422_not_500(self, client):
        token = _signup(client, "link1@example.com")
        net_data = _make_single_place_net_data()

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={
                "objects": [{"net_data": net_data}],
                "links": [
                    {
                        "type": "placeFusion",
                        "source_object": -1,
                        "source_element": 0,
                        "target_object": 0,
                        "target_element": 0,
                    }
                ],
            },
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_zero_quantity_link_returns_422_not_500(self, client):
        token = _signup(client, "link2@example.com")
        net_data = _make_single_place_net_data()

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={
                "objects": [{"net_data": net_data}],
                "links": [
                    {
                        "type": "placeFusion",
                        "source_object": 0,
                        "source_element": 0,
                        "target_object": 0,
                        "target_element": 0,
                        "quantity": 0,
                    }
                ],
            },
            headers=_auth(token),
        )
        assert resp.status_code == 422


class TestComposedStreamPayload:
    """Covers the SSE body this router writes, not just its rejection paths.

    That body had no test at all, which is exactly why firing_sequence was
    serialized by simulate.py and sessions.py but silently missing here: the
    three SSE loops are near-copies, and only two of them were pinned down.
    """

    def _stream_one(self, client, monkeypatch, event, email: str):
        import src.api.versions.v1.routers.simulate_composed as router_mod

        # Both settings: a URL alone no longer routes a run to the external
        # engine, the deployment has to have asked for it.
        monkeypatch.setattr("src.core.config.settings.SIMULATION_ENGINE", "remote")
        monkeypatch.setattr(
            "src.core.config.settings.SIMULATION_REMOTE_URL", "http://petri-server:8080"
        )

        async def _fake_remote(*args, **kwargs):
            yield event

        monkeypatch.setattr(router_mod, "run_remote_streaming_v2", _fake_remote)

        token = _signup(client, email)
        resp = client.post(
            "/api/v1/simulate/composed",
            json={"objects": [{"net_data": _make_single_place_net_data()}]},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        return resp.text

    def test_stream_carries_firing_sequence(self, client, monkeypatch):
        import json

        from src.services.simulation.engine import FiringStep, SimulationEvent

        event = SimulationEvent(
            current_time=1.5,
            step_number=2,
            markings={"p1": 1, "p2": 0},
            buffers={"t1": 1},
            progress=0.15,
            fired_transitions=["t1"],
            firing_sequence=[
                FiringStep(
                    transition_id="t1",
                    phase="before_act_in",
                    markings={"p1": 2, "p2": 0},
                    buffers={"t1": 0},
                    time=1.5,
                )
            ],
        )

        body = self._stream_one(client, monkeypatch, event, "stream1@example.com")
        frames = [chunk.strip() for chunk in body.split("data: ") if chunk.strip()]
        assert frames[-1] == "[DONE]"

        frame = json.loads(frames[0])
        assert frame["current_time"] == 1.5
        assert frame["fired_transitions"] == ["t1"]
        assert frame["firing_sequence"] == [
            {
                "transition_id": "t1",
                "phase": "before_act_in",
                "markings": {"p1": 2, "p2": 0},
                "buffers": {"t1": 0},
                "time": 1.5,
            }
        ]

    def test_stream_emits_empty_sequence_when_nothing_fired(self, client, monkeypatch):
        """The key is always present, never null — the frontend reads its
        length before deciding whether to expand the frame into phases."""
        import json

        from src.services.simulation.engine import SimulationEvent

        event = SimulationEvent(
            current_time=0.0,
            step_number=0,
            markings={"p1": 1},
            buffers={},
            progress=0.0,
        )

        body = self._stream_one(client, monkeypatch, event, "stream2@example.com")
        frame = json.loads(body.split("data: ")[1].strip())
        assert frame["firing_sequence"] == []
        assert frame["fired_transitions"] == []


class TestComposedRateLimit:
    def test_preview_returns_429_when_limit_exceeded(self, client, monkeypatch):
        token = _signup(client, "rl1@example.com")
        net_data = _make_single_place_net_data()

        async def over_limit(key, max_requests, window):
            return False, max_requests + 1, 30

        monkeypatch.setattr("src.api.shared.rate_limit._hit", over_limit)

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={"objects": [{"net_data": net_data}]},
            headers=_auth(token),
        )
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "30"


class TestComposedModelValidationErrors:
    """An invalid model must come back as an actionable 400, never a 500.

    The raise site used to shape details as {"error": ...}, which the API
    exception handler (whose response model wants {field, message}) answered
    by crashing — the pydantic error inside the handler turned the one
    message a canvas user could act on into a bare 500, which the frontend
    then reported as "the simulation service is unavailable".
    """

    def test_transition_without_input_arc_is_a_400_with_the_message(self, client):
        token = _signup(client, "composed-validation@example.com")
        body = {
            "name": "Invalid",
            "objects": [
                {
                    "name": "Object_1",
                    "priority": 0,
                    "x": 0,
                    "y": 0,
                    "net_data": {
                        "places": [
                            {"id": "p1", "name": "p1", "tokens": 1, "graphics": {"x": 0, "y": 0}}
                        ],
                        "transitions": [
                            {
                                "id": "t1",
                                "name": "T_1",
                                "priority": 1,
                                "distribution": "exp",
                                "mean_delay": 1.0,
                                "standard_deviation": 0.0,
                                "probability": None,
                                "graphics": {"x": 50, "y": 0},
                            }
                        ],
                        "arcs": [],
                    },
                }
            ],
            "links": [],
        }

        resp = client.post(
            "/api/v1/simulate/composed?simulation_time=10",
            json=body,
            headers=_auth(token),
        )

        assert resp.status_code == 400, resp.text
        error = resp.json()["error"]
        assert error["message"] == "Composed model is invalid"
        details = error["details"]
        assert details, "the validation messages must survive into the response"
        assert details[0]["field"] == "model"
        assert "no consuming input" in details[0]["message"]

    def test_a_place_fusion_rule_violation_is_also_a_400_with_the_message(self, client):
        """desktop #61/#62: `ComposedModel.validate()` now also runs the five
        placeFusion rules (`place_fusion_rejection`), and this router calls
        `validate()` on every request (`_resolve_composed_model`) before a
        simulation or a preview ever starts -- so a request built by a
        client that skips the editor's own checks (or a second client
        entirely) is refused the same actionable way a structurally invalid
        net already was, never as an opaque 500."""
        token = _signup(client, "composed-fusion-validation@example.com")
        body = {
            "name": "SelfLinked",
            "objects": [{"name": "Object_1", "net_data": _make_single_place_net_data()}],
            "links": [
                {
                    "type": "placeFusion",
                    "source_object": 0,
                    "source_element": 0,
                    "target_object": 0,
                    "target_element": 0,
                }
            ],
        }

        resp = client.post(
            "/api/v1/simulate/composed?simulation_time=10",
            json=body,
            headers=_auth(token),
        )

        assert resp.status_code == 400, resp.text
        error = resp.json()["error"]
        assert error["message"] == "Composed model is invalid"
        details = error["details"]
        assert details, "the validation messages must survive into the response"
        assert details[0]["field"] == "model"
        assert "cannot be linked to itself" in details[0]["message"]


class TestSimulationErrorVocabulary:
    """A 4xx from petri-server carries the engine's own rejection text and is
    labeled model-vocabulary, so the frontend shows it verbatim instead of
    the service-unavailable wording; everything else stays transport."""

    def _status_error(self, status: int, body: str, content_type: str = "application/json"):
        import httpx

        request = httpx.Request("POST", "http://petri-server:8080/v2/simulate")
        response = httpx.Response(
            status, content=body.encode(), headers={"content-type": content_type}, request=request
        )
        return httpx.HTTPStatusError("boom", request=request, response=response)

    def test_engine_4xx_json_message_is_model_vocabulary(self):
        from src.api.versions.v1.routers.simulate_composed import _simulation_error_message

        exc = self._status_error(400, '{"message": "link 0 connects object 0 to itself"}')
        message, kind = _simulation_error_message(exc, "http://petri-server:8080")
        assert kind == "model"
        assert "connects object 0 to itself" in message

    def test_engine_4xx_plain_text_is_model_vocabulary(self):
        from src.api.versions.v1.routers.simulate_composed import _simulation_error_message

        exc = self._status_error(422, "T_1 has no input positions", content_type="text/plain")
        message, kind = _simulation_error_message(exc, "http://petri-server:8080")
        assert kind == "model"
        assert "T_1 has no input positions" in message

    def test_engine_5xx_stays_transport(self):
        from src.api.versions.v1.routers.simulate_composed import _simulation_error_message

        exc = self._status_error(500, "boom")
        message, kind = _simulation_error_message(exc, "http://petri-server:8080")
        assert kind == "transport"
        assert "HTTP 500" in message

    def test_exporter_valueerror_is_model_vocabulary_not_transport(self):
        """A ValueError raised by the composed PNML exporter (an invalid or
        duplicate element id, a cross-page arc) happens inside this process,
        before any request reaches petri-server, it is a problem with the
        model, not the deployment, so it must not be labeled "transport"."""
        from src.api.versions.v1.routers.simulate_composed import _simulation_error_message

        exc = ValueError("Object 0 ('A') has a duplicate element id 'p1', cannot export")
        message, kind = _simulation_error_message(exc, "http://petri-server:8080")
        assert kind == "model"
        assert "duplicate element id" in message


class TestPreviewExportValueError:
    """/preview must answer a model that fails to export with a 400 naming
    the problem, not an unhandled 500: the exporter's ValueError runs inside
    `parse_composed_model_remote`, before any network call, and used to
    propagate past every except clause the route had."""

    def test_a_duplicate_id_within_one_object_is_a_400_not_a_500(self, client, monkeypatch):
        """Two places sharing an id within one object clears
        `ComposedModel.validate()` (that only checks NCName-ness, not
        uniqueness) and fails at export time instead."""
        monkeypatch.setattr(
            "src.core.config.settings.SIMULATION_REMOTE_URL", "http://127.0.0.1:1"
        )
        token = _signup(client, "previewval1@example.com")
        net_data = {
            "places": [
                {"id": "p1", "name": "A", "tokens": 0, "graphics": {"x": 0, "y": 0}},
                {"id": "p1", "name": "B", "tokens": 0, "graphics": {"x": 0, "y": 0}},
            ],
            "transitions": [],
            "arcs": [],
        }

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={"objects": [{"net_data": net_data}]},
            headers=_auth(token),
        )

        assert resp.status_code == 400
        error = resp.json()["error"]
        details = error["details"]
        assert details, "the exporter's message must survive into the response"
        assert "duplicate element id" in details[0]["message"]

    def test_a_duplicate_id_is_a_400_through_the_local_validator_too(self, client, monkeypatch):
        """The same export-time ValueError, but with no remote configured:
        _local_preview must be reachable through the SAME except ValueError
        handling as the remote path, not let it escape uncaught."""
        monkeypatch.setattr("src.core.config.settings.SIMULATION_REMOTE_URL", None)
        token = _signup(client, "previewval-local@example.com")
        net_data = {
            "places": [
                {"id": "p1", "name": "A", "tokens": 0, "graphics": {"x": 0, "y": 0}},
                {"id": "p1", "name": "B", "tokens": 0, "graphics": {"x": 0, "y": 0}},
            ],
            "transitions": [],
            "arcs": [],
        }

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={"objects": [{"net_data": net_data}]},
            headers=_auth(token),
        )

        assert resp.status_code == 400
        details = resp.json()["error"]["details"]
        assert details, "the exporter's message must survive into the response"
        assert "duplicate element id" in details[0]["message"]


class TestPreviewLocalFallback:
    """SIMULATION_REMOTE_URL unset: /preview validates locally instead of
    refusing outright, by round-tripping the exported PNML through this
    application's own importer (services/petri/importer)."""

    def test_reports_objects_and_links(self, client, monkeypatch):
        monkeypatch.setattr("src.core.config.settings.SIMULATION_REMOTE_URL", None)
        token = _signup(client, "localfallback1@example.com")
        object_a = _make_single_place_net_data()
        object_b = _make_single_place_net_data()
        object_b["places"][0]["id"] = "p2"

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={
                "objects": [
                    {"name": "A", "net_data": object_a},
                    {"name": "B", "net_data": object_b},
                ],
                "links": [
                    {
                        "type": "placeFusion",
                        "source_object": 0,
                        "source_element": 0,
                        "target_object": 1,
                        "target_element": 0,
                    }
                ],
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["validator"] == "local"
        assert {o["name"] for o in data["objects"]} == {"A", "B"}
        assert len(data["links"]) == 1
        assert data["warnings"] == []

    def test_does_not_reach_the_network(self, client, monkeypatch):
        """No httpx call should be made at all when the local fallback runs
        -- proof this genuinely never touches a remote backend, rather than
        happening to succeed against one reachable by coincidence."""
        import httpx

        monkeypatch.setattr("src.core.config.settings.SIMULATION_REMOTE_URL", None)

        async def _fail(*args, **kwargs):
            raise AssertionError("must not make a network call for the local fallback")

        monkeypatch.setattr(httpx.AsyncClient, "post", _fail)

        token = _signup(client, "localfallback2@example.com")
        net_data = _make_single_place_net_data()

        resp = client.post(
            "/api/v1/simulate/composed/preview",
            json={"objects": [{"net_data": net_data}]},
            headers=_auth(token),
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["validator"] == "local"


class TestPreviewNonJsonResponseIsTransportNotModel:
    """A 200 response whose body is not JSON is petri-server (or whatever
    sits in front of it) answering with something unreadable, a transport
    problem, not the exporter rejecting the model. `resp.json()` raises
    `json.JSONDecodeError`, which subclasses `ValueError`, so this used to
    be caught by the same `except ValueError` branch as a genuine exporter
    invariant violation and misreported as a 400 model rejection instead of
    the 503 every other transport failure gets."""

    def test_non_json_200_body_is_503_not_400(self, client, monkeypatch):
        monkeypatch.setattr(
            "src.core.config.settings.SIMULATION_REMOTE_URL", "http://petri-server:8080"
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            side_effect=json.JSONDecodeError("Expecting value", "<html>not json</html>", 0)
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        token = _signup(client, "previewjson1@example.com")
        net_data = _make_single_place_net_data()

        with patch(
            "src.services.simulation.remote_v2.httpx.AsyncClient", return_value=mock_client
        ):
            resp = client.post(
                "/api/v1/simulate/composed/preview",
                json={"objects": [{"net_data": net_data}]},
                headers=_auth(token),
            )

        assert resp.status_code == 503
