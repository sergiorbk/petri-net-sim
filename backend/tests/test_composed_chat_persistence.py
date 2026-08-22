"""Tests for contract phase-2 part D: composed net_data (Petri-objects)
round-tripping through the chat persistence layer and the session-scoped
REST endpoints.

Three things this verifies:
  1. The structural hash the chat service uses to decide whether to
     persist a new snapshot (_net_structure_hash in openai_chat_service.py)
     covers `objects`/`links`, not just `places`/`transitions`/`arcs` --
     a link-only or object-rename-only edit must still be seen as a real
     structural change.
  2. GET /sessions/{id}/net serves a composed session's net_data back
     exactly as stored (objects/links intact, only the backend-internal
     underscore-prefixed keys stripped) -- this is the shape the frontend
     editor handoff (SimulationResultRenderer -> useEditorStore.setNet)
     consumes with no changes of its own, see the report for why that path
     needed no frontend fix.
  3. The session-scoped REST /simulate, /simulate/precompute and
     /shared/{token}/simulate endpoints refuse composed net_data with the
     established clear error (422 / SSE error frame) instead of routing it
     through the flat-only engine, where it would not crash (pydantic
     ignores the unknown objectId/objects/links keys) but would silently
     produce a wrong result -- colliding ids across objects, and a
     transitionToPlace/placeFusion link dropped entirely since it has no
     local arc to flatten into.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.session import Session as SessionModel
from src.infrastructure.postgres.models.user import User
from src.services.petri.agent_toolkit import operations as ops
from src.services.petri.agent_toolkit.errors import ToolError
from src.services.petri.session import PetriNetSession


def _ok(result) -> str:
    assert not isinstance(result, ToolError), f"expected success, got: {result}"
    return str(result)


def _two_object_fused_net_data() -> dict:
    """Same A/PA/TA + B/PB/TB placeFusion scenario Part B's composed-
    simulate smoke test uses, built through the real ops layer so this
    fixture only ever exercises real tool behavior."""
    session = PetriNetSession()
    _ok(ops.op_create_object(session, name="A"))
    _ok(ops.op_add_place(session, name="PA", tokens=1))
    _ok(ops.op_add_transition(session, name="TA"))
    a_place = session.net.places[0].id
    a_trans = session.net.transitions[0].id
    _ok(ops.op_add_arc(session, source_id=a_place, target_id=a_trans))

    _ok(ops.op_create_object(session, name="B"))
    _ok(ops.op_add_place(session, name="PB", tokens=0))
    _ok(ops.op_add_transition(session, name="TB"))
    b_place = session.net.places[0].id
    b_trans = session.net.transitions[0].id
    _ok(ops.op_add_arc(session, source_id=b_place, target_id=b_trans))

    _ok(ops.op_link_objects(
        session, link_type="placeFusion",
        source_object="B", source_element="PB",
        target_object="A", target_element="PA",
    ))
    return session.to_net_data()


def _sid() -> str:
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()


# ---------------------------------------------------------------------------
# 1. Structural hash covers objects/links
# ---------------------------------------------------------------------------


class TestStructuralHashCoversObjectsAndLinks:
    def test_hash_changes_when_a_link_is_added_with_no_place_transition_arc_change(self):
        from src.services.chat.openai_chat_service import _net_structure_hash

        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="PA", tokens=1))
        _ok(ops.op_create_object(session, name="B"))
        _ok(ops.op_add_place(session, name="PB", tokens=0))
        before = session.to_net_data()
        before_hash = _net_structure_hash(before)

        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="B", source_element="PB",
            target_object="A", target_element="PA",
        ))
        after = session.to_net_data()
        after_hash = _net_structure_hash(after)

        # No place, transition or arc was added, removed or re-owned: a
        # placeFusion needs no local arc. Coordinates are excluded on
        # purpose -- the link IS the statement that one object now follows
        # the other, so it re-arranges them (_arrange_object_frames), which
        # is exactly the change the hash has to notice.
        def _identity(elements: list[dict]) -> list[tuple]:
            return [
                (e["id"], e["name"], e.get("objectId")) for e in elements
            ]

        assert _identity(before["places"]) == _identity(after["places"])
        assert _identity(before["transitions"]) == _identity(after["transitions"])
        assert before["arcs"] == after["arcs"]
        assert "links" not in before or not before["links"]
        assert after["links"]
        assert before_hash != after_hash

    def test_linking_two_objects_rearranges_them(self):
        """The other half of the same fact: a hand-off is an ordering, so
        the object that feeds the other is drawn before it.

        The direction comes from the NET, not from which endpoint was named
        first -- a place fusion says two places are one place, and that is
        symmetric. So the objects here really do write and read: Feeder
        produces into its place, Drain consumes from its own. The link is
        deliberately stated backwards, Drain first, and the drawing still
        puts Feeder ahead."""
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="Feeder"))
        _ok(ops.op_add_place(session, name="Out", tokens=0))
        _ok(ops.op_add_transition(session, name="Emit"))
        feeder = session.objects[0].net
        _ok(ops.op_add_arc(
            session,
            source_id=feeder.transitions[0].id,
            target_id=feeder.places[0].id,
        ))
        _ok(ops.op_create_object(session, name="Drain"))
        _ok(ops.op_add_place(session, name="In", tokens=0))
        _ok(ops.op_add_transition(session, name="Consume"))
        drain = session.objects[1].net
        _ok(ops.op_add_arc(
            session,
            source_id=drain.places[0].id,
            target_id=drain.transitions[0].id,
        ))
        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="Drain", source_element="In",
            target_object="Feeder", target_element="Out",
        ))

        frames = {o["name"]: o["graphics"] for o in session.to_net_data()["objects"]}
        assert frames["Feeder"]["x"] < frames["Drain"]["x"]

    def test_hash_changes_on_object_rename_alone(self):
        from src.services.chat.openai_chat_service import _net_structure_hash

        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="PA", tokens=1))
        before_hash = _net_structure_hash(session.to_net_data())

        _ok(ops.op_rename_object(session, name="A", new_name="Loader"))
        after_hash = _net_structure_hash(session.to_net_data())

        assert before_hash != after_hash

    def test_hash_is_stable_across_underscore_bookkeeping_churn(self):
        """The hash must NOT change when only internal tracking keys
        change (e.g. _is_optimized flipping) -- it strips every key
        starting with '_', composed or not."""
        from src.services.chat.openai_chat_service import _net_structure_hash

        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="PA", tokens=1))
        data = session.to_net_data()
        mutated = dict(data)
        mutated["_is_optimized"] = not data.get("_is_optimized")
        mutated["_last_simulation_result_text"] = "unrelated bookkeeping change"

        assert _net_structure_hash(data) == _net_structure_hash(mutated)

    def test_hash_matches_the_snapshot_repository_content_hash_formula(self):
        """session_service.save_snapshot_and_net computes its own
        content_hash the same way (sha256 of the sort_keyed JSON dump,
        default=str) -- both must treat objects/links as structural."""
        import hashlib as _hashlib
        import json as _json

        from src.services.chat.openai_chat_service import _net_structure_hash

        net_data = _two_object_fused_net_data()
        clean = {k: v for k, v in net_data.items() if not k.startswith("_")}
        expected = _hashlib.sha256(
            _json.dumps(clean, sort_keys=True, default=str).encode()
        ).hexdigest()
        assert _net_structure_hash(net_data) == expected


# ---------------------------------------------------------------------------
# 2 & 3. REST endpoints: app/client fixtures (mirrors test_sessions_api.py)
# ---------------------------------------------------------------------------


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


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 2. GET /sessions/{id}/net serves the composed shape as stored
# ---------------------------------------------------------------------------


class TestGetSessionNetServesComposedShape:
    @pytest.mark.anyio
    async def test_objects_and_links_survive_the_round_trip(self, client, session, password_user):
        net_data = _two_object_fused_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        response = client.get(f"/api/v1/sessions/{s.id}/net", headers=_auth(token))
        assert response.status_code == 200
        data = response.json()["data"]

        assert len(data["objects"]) == 2
        assert {o["name"] for o in data["objects"]} == {"A", "B"}
        assert len(data["links"]) == 1
        assert data["links"][0]["type"] == "placeFusion"
        # Every place still carries its owning object.
        object_ids = {o["id"] for o in data["objects"]}
        for place in data["places"]:
            assert place.get("objectId") in object_ids

    @pytest.mark.anyio
    async def test_internal_keys_still_stripped_on_a_composed_session(
        self, client, session, password_user
    ):
        net_data = _two_object_fused_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        response = client.get(f"/api/v1/sessions/{s.id}/net", headers=_auth(token))
        data = response.json()["data"]
        assert "_last_output_place_id" not in data
        assert "_last_pnml_export" not in data

    @pytest.mark.anyio
    async def test_reloaded_session_continues_editing_the_same_composed_model(
        self, client, session, password_user
    ):
        """The editor-handoff round trip: fetch net_data back from the
        REST endpoint, rehydrate a PetriNetSession from exactly that dict
        (as tool_node does for the next chat turn), and confirm both
        objects, the fusion link, and the free pool are all still there --
        this is what lets an object add a place after a reload."""
        net_data = _two_object_fused_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        response = client.get(f"/api/v1/sessions/{s.id}/net", headers=_auth(token))
        fetched = response.json()["data"]

        reloaded = PetriNetSession.from_net_data(fetched)
        assert reloaded.is_composed
        assert {o.name for o in reloaded.objects} == {"A", "B"}
        assert len(reloaded.links) == 1

        idx = reloaded.find_object_index("A")
        reloaded.set_active_object(idx)
        _ok(ops.op_add_place(reloaded, name="NewInA", tokens=0))

        new_data = reloaded.to_net_data()
        a_frame_id = next(o["id"] for o in new_data["objects"] if o["name"] == "A")
        assert any(
            p["name"] == "NewInA" and p.get("objectId") == a_frame_id
            for p in new_data["places"]
        )
        # The fusion link and object B are untouched by the reload+edit.
        assert len(new_data["links"]) == 1
        assert any(o["name"] == "B" for o in new_data["objects"])


# ---------------------------------------------------------------------------
# 3. Session-scoped simulate endpoints reject composed net_data cleanly
# ---------------------------------------------------------------------------


class TestSimulateEndpointsRejectComposedNetData:
    def test_simulate_with_inline_composed_net_data_returns_clear_sse_error(self, client):
        from src.services.auth.jwt_service import get_jwt_service
        # No DB needed for the inline net_data path -- sign up for a token.
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": "composed-sim@example.com", "password": "password123"},
        )
        assert signup.status_code == 200
        token = signup.json()["data"]["access_token"]

        net_data = _two_object_fused_net_data()
        resp = client.post(
            "/api/v1/sessions/dummy_session/simulate?simulation_time=10",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 200  # SSE endpoints answer 200 then stream an error frame
        body = resp.text
        assert "Petri-objects" in body
        assert "[DONE]" in body
        # Must NOT have silently run the flat engine and reported a result.
        assert '"markings"' not in body

    @pytest.mark.anyio
    async def test_simulate_uses_composed_session_net_data_returns_clear_error(
        self, client, session, password_user
    ):
        net_data = _two_object_fused_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        await session.commit()

        from src.services.auth.jwt_service import get_jwt_service
        token = get_jwt_service().create_access_token(password_user.id, password_user.email)

        resp = client.post(
            f"/api/v1/sessions/{s.id}/simulate?simulation_time=10",
            json={},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert "Petri-objects" in resp.text
        assert "/simulate/composed" in resp.text

    def test_precompute_with_composed_net_data_returns_422_not_500(self, client):
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": "composed-pre@example.com", "password": "password123"},
        )
        token = signup.json()["data"]["access_token"]

        net_data = _two_object_fused_net_data()
        resp = client.post(
            "/api/v1/sessions/dummy/simulate/precompute?simulation_time=10",
            json={"net_data": net_data},
            headers=_auth(token),
        )

        assert resp.status_code == 422
        assert "Petri-objects" in resp.text

    @pytest.mark.anyio
    async def test_shared_simulate_with_composed_session_returns_clear_error_not_500(
        self, client, session, password_user
    ):
        net_data = _two_object_fused_net_data()
        s = await _create_db_session(session, password_user, net_data=net_data)
        s.visibility = "link_only"
        await session.flush()
        await session.commit()

        resp = client.post(
            f"/api/v1/sessions/shared/{s.share_token}/simulate?simulation_time=10",
            json={},
        )
        assert resp.status_code == 200
        assert "Petri-objects" in resp.text
        assert "[DONE]" in resp.text

    def test_flat_net_data_still_simulates_normally(self, client):
        """Control: an ordinary flat net (no objects/links at all) must
        NOT hit the new guard -- proves the composed check is additive,
        not a regression on the existing, far more common case."""
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": "flat-control@example.com", "password": "password123"},
        )
        token = signup.json()["data"]["access_token"]

        session = PetriNetSession()
        session.create_network("Flat")
        gen = session.builder.add_generator("Gen1", interval=5.0)
        machine = session.builder.add_machine("Server", processing_time=2.0)
        term = session.builder.add_terminator("Exit")
        session.builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
        session.builder.connect(machine.interface.output_place_id, term.interface.input_place_id)
        net_data = session.to_net_data()
        net_data.pop("_last_output_place_id", None)
        net_data.pop("_has_custom_topology", None)

        resp = client.post(
            "/api/v1/sessions/dummy_session/simulate?simulation_time=10&time_step=5",
            json={"net_data": net_data},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert "Petri-objects" not in resp.text
        assert "[DONE]" in resp.text
