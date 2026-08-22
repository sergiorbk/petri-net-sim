"""Tests for /v1/nets/{net_id}/pnml -- the PNML download route added
alongside the Python PNML importer/import_pnml work (contract part B).
The rest of /v1/nets/* is exercised end-to-end here already through
these same POST/GET calls; no separate suite pre-existed for this router.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_app() -> FastAPI:
    from src.api.shared.exceptions import ApiException
    from src.api.shared.handlers import api_exception_handler
    from src.api.versions.v1.routers.auth import router as auth_router
    from src.api.versions.v1.routers.nets import router as nets_router

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.add_exception_handler(ApiException, api_exception_handler)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(nets_router, prefix="/api/v1")
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


def _signup(client: TestClient, email: str = "netuser@example.com") -> str:
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _flat_net_data() -> dict:
    from src.services.petri.session import PetriNetSession

    s = PetriNetSession()
    s.create_network("Flat Net")
    s.builder.add_raw_place("P1")
    return s.to_net_data()


def _composed_net_data() -> dict:
    from src.domain.composed import LinkType
    from src.services.petri.session import PetriNetSession

    s = PetriNetSession()
    s.create_object("Loader")
    p1 = s.builder.add_raw_place("P1")
    s.create_object("Sink")
    p2 = s.builder.add_raw_place("P2")
    s.set_active_object(0)
    t1 = s.builder.add_raw_transition("T1", mean_delay=1.0)
    s.net.add_arc(source_id=p1, target_id=t1)
    s.add_link(
        LinkType.TRANSITION_TO_PLACE,
        s.objects[0].frame_id, t1,
        s.objects[1].frame_id, p2,
    )
    return s.to_net_data()


def _create_net(client: TestClient, token: str, name: str, net_data: dict) -> str:
    resp = client.post(
        "/api/v1/nets",
        json={"name": name, "net_data": net_data},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


class TestGetUserNetPnml:
    def test_returns_downloadable_xml(self, client):
        token = _signup(client, "pnml1@example.com")
        net_id = _create_net(client, token, "My Net", _flat_net_data())

        response = client.get(f"/api/v1/nets/{net_id}/pnml", headers=_auth(token))

        assert response.status_code == 200, response.text
        assert "xml" in response.headers["content-type"]
        disposition = response.headers["content-disposition"]
        assert "attachment" in disposition
        assert ".pnml" in disposition
        assert "<?xml" in response.text
        assert "Flat Net" in response.text

    def test_uses_composed_dialect_when_composed(self, client):
        """A composed net's exported PNML round-trips through the importer
        back into objects/links, proving the composed dialect was used."""
        from src.services.petri.importer import parse_pnml

        token = _signup(client, "pnml2@example.com")
        net_id = _create_net(client, token, "Composed", _composed_net_data())

        response = client.get(f"/api/v1/nets/{net_id}/pnml", headers=_auth(token))

        assert response.status_code == 200, response.text
        net_data, warnings = parse_pnml(response.text)
        assert warnings == []
        assert {o["name"] for o in net_data["objects"]} == {"Loader", "Sink"}
        assert len(net_data["links"]) == 1

    def test_nonexistent_returns_404(self, client):
        import uuid

        token = _signup(client, "pnml3@example.com")
        response = client.get(f"/api/v1/nets/{uuid.uuid4()}/pnml", headers=_auth(token))
        assert response.status_code == 404

    def test_cannot_read_other_users_net(self, client):
        owner_token = _signup(client, "pnml-owner@example.com")
        net_id = _create_net(client, owner_token, "Private", _flat_net_data())

        attacker_token = _signup(client, "pnml-attacker@example.com")
        response = client.get(f"/api/v1/nets/{net_id}/pnml", headers=_auth(attacker_token))
        assert response.status_code == 404

    def test_unauthenticated_returns_401_or_403(self, client):
        import uuid

        response = client.get(f"/api/v1/nets/{uuid.uuid4()}/pnml")
        assert response.status_code in (401, 403)
