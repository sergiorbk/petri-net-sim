"""Tests for POST /v1/pnml/parse -- the standalone PNML parse route
(contract part B): auth like the sibling standalone /simulate route, and
a 400 for the two hard PNML failures rather than an unhandled 500.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.security_config import security_settings
from tests.test_pnml_importer import SAMPLE_PNML


def _create_test_app() -> FastAPI:
    from src.api.shared.exceptions import ApiException
    from src.api.shared.handlers import api_exception_handler
    from src.api.versions.v1.routers.auth import router as auth_router
    from src.api.versions.v1.routers.pnml import router as pnml_router

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.add_exception_handler(ApiException, api_exception_handler)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(pnml_router, prefix="/api/v1")
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


def _signup(client: TestClient, email: str = "pnmlparse@example.com") -> str:
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestParsePnml:
    def test_unauthenticated_returns_401_or_403(self, client):
        response = client.post("/api/v1/pnml/parse", json={"xml": SAMPLE_PNML})
        assert response.status_code in (401, 403)

    def test_parses_a_well_formed_document(self, client):
        token = _signup(client, "parse1@example.com")
        response = client.post(
            "/api/v1/pnml/parse", json={"xml": SAMPLE_PNML}, headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["net_data"]["name"] == "Test Net"
        assert len(body["net_data"]["places"]) == 2
        assert body["warnings"] == []

    def test_reports_warnings_without_failing(self, client):
        token = _signup(client, "parse2@example.com")
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Bad ids</text></name>
    <place id="my place"><name><text>My Place</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="my place" target="t1"><inscription><text>1</text></inscription></arc>
  </net>
</pnml>"""
        response = client.post(
            "/api/v1/pnml/parse", json={"xml": xml}, headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["net_data"]["places"][0]["id"] == "my-place"
        codes = [w["code"] for w in body["warnings"]]
        assert "invalid-id" in codes

    def test_missing_pnml_root_is_a_400_not_a_500(self, client):
        token = _signup(client, "parse3@example.com")
        response = client.post(
            "/api/v1/pnml/parse", json={"xml": "<not-pnml/>"}, headers=_auth(token),
        )
        assert response.status_code == 400, response.text
        assert "pnml" in response.json()["error"]["message"].lower()

    def test_missing_net_element_is_a_400(self, client):
        token = _signup(client, "parse4@example.com")
        xml = '<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml"></pnml>'
        response = client.post(
            "/api/v1/pnml/parse", json={"xml": xml}, headers=_auth(token),
        )
        assert response.status_code == 400, response.text
        assert "net" in response.json()["error"]["message"].lower()

    def test_not_well_formed_xml_is_a_400(self, client):
        token = _signup(client, "parse5@example.com")
        response = client.post(
            "/api/v1/pnml/parse", json={"xml": "<pnml><net"}, headers=_auth(token),
        )
        assert response.status_code == 400, response.text


class TestParsePnmlSecurityDefenses:
    """Part B, item 4: POST /pnml/parse carries the same per-credential
    rate-limit dependency as the standalone POST /simulate route (mirrors
    TestComposedRateLimit in test_simulate_composed_api.py), and
    /api/v1/pnml is one of the large-body-cap path prefixes in
    security_config.py -- like /simulate, it legitimately accepts a full
    net's worth of content, just as PNML/XML.
    """

    def test_rate_limit_dependency_present(self, client, monkeypatch):
        token = _signup(client, "pnmlratelimit@example.com")

        async def over_limit(key, max_requests, window):
            return False, max_requests + 1, 30

        monkeypatch.setattr("src.api.shared.rate_limit._hit", over_limit)

        response = client.post(
            "/api/v1/pnml/parse", json={"xml": SAMPLE_PNML}, headers=_auth(token),
        )
        assert response.status_code == 429
        assert response.headers.get("Retry-After") == "30"

    def test_oversized_body_is_rejected(self, monkeypatch, session_factory):
        """A body under the plain default cap but over it is accepted here
        (proving /api/v1/pnml got the higher, large-body cap, not the
        default one), while one that overruns even the large cap is still
        rejected with 413 -- the endpoint is covered by the size limiter
        at all, just at the larger ceiling /simulate also gets.
        """
        from fastapi import FastAPI

        from src.api.shared.security_middleware import BodySizeLimitMiddleware
        from src.core.dependencies import get_postgres_session

        monkeypatch.setattr(security_settings, "SECURITY_MAX_BODY_BYTES", 200)
        monkeypatch.setattr(security_settings, "SECURITY_MAX_BODY_BYTES_LARGE", 2_000)

        app = _create_test_app()
        app.add_middleware(BodySizeLimitMiddleware)

        async def _override_session():
            async with session_factory() as sess:
                yield sess

        app.dependency_overrides[get_postgres_session] = _override_session
        with TestClient(app, raise_server_exceptions=False) as body_client:
            token = _signup(body_client, "pnmlbodylimit@example.com")

            # ~1KB: over the 200-byte default cap, under the 2000-byte large one.
            under_large_cap = body_client.post(
                "/api/v1/pnml/parse",
                json={"xml": "<pnml>" + ("x" * 1_000) + "</pnml>"},
                headers=_auth(token),
            )
            assert under_large_cap.status_code != 413, under_large_cap.text

            over_large_cap = body_client.post(
                "/api/v1/pnml/parse",
                json={"xml": "<pnml>" + ("x" * 3_000) + "</pnml>"},
                headers=_auth(token),
            )
            assert over_large_cap.status_code == 413
