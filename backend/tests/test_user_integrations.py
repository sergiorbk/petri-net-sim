"""Tests for the per-user integration switches (MCP / HTTP API).

Covers the storage helpers, the PATCH /me round trip, and the two places
that enforce a switched-off integration.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from src.api.shared.exceptions import ApiException
from src.api.shared.handlers import api_exception_handler
from src.services.auth.integrations import (
    HTTP_API,
    MCP,
    apply_integration,
    integration_enabled,
    read_integrations,
)
from src.services.auth.jwt_service import get_jwt_service

DB_MODULE = "src.infrastructure.postgres.database"


class _FakeUser:
    def __init__(self, metadata):
        self.metadata_ = metadata


# -- storage helpers --


class TestIntegrationFlags:
    def test_absent_metadata_reads_as_enabled(self):
        """Accounts that predate the switch keep working untouched."""
        assert integration_enabled(_FakeUser(None), MCP) is True
        assert integration_enabled(_FakeUser({}), HTTP_API) is True

    def test_malformed_flags_read_as_enabled(self):
        """A garbled metadata value must not silently lock a user out."""
        assert integration_enabled(_FakeUser({"integrations": "yes"}), MCP) is True
        assert integration_enabled(_FakeUser({"integrations": {"mcp": "no"}}), MCP) is True

    def test_only_false_disables(self):
        assert integration_enabled(_FakeUser({"integrations": {"mcp": False}}), MCP) is False
        assert integration_enabled(_FakeUser({"integrations": {"mcp": True}}), MCP) is True

    def test_switches_are_independent(self):
        meta = apply_integration({}, MCP, False)
        user = _FakeUser(meta)
        assert integration_enabled(user, MCP) is False
        assert integration_enabled(user, HTTP_API) is True

    def test_apply_does_not_edit_the_mapping_it_was_given(self):
        """The nested dict is rebuilt, not mutated.

        Callers hand in a shallow copy of User.metadata_, so an in-place
        edit would also change SQLAlchemy's committed value for the column:
        the flush would find nothing to write and the switch would stop
        taking after its first use.
        """
        stored = {"mcp": True}
        meta = {"integrations": stored}

        apply_integration(meta, MCP, False)

        assert stored == {"mcp": True}
        assert meta["integrations"] == {"mcp": False}

    def test_apply_preserves_unrelated_metadata(self):
        meta = apply_integration({"display_name": "Ada"}, HTTP_API, False)
        assert meta["display_name"] == "Ada"
        assert meta["integrations"] == {HTTP_API: False}

    def test_read_integrations_reports_both(self):
        user = _FakeUser(apply_integration({}, MCP, False))
        assert read_integrations(user) == {MCP: False, HTTP_API: True}


# -- PATCH /me --


def _create_test_app():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.add_exception_handler(ApiException, api_exception_handler)

    from src.api.versions.v1.routers.auth import router as auth_router

    app.include_router(auth_router, prefix="/api/v1")
    return app


@pytest.fixture
def client(session_factory):
    app = _create_test_app()
    with patch(f"{DB_MODULE}.AsyncSessionLocal", new=session_factory):
        from src.core.dependencies import get_postgres_session

        async def _override_session():
            async with session_factory() as sess:
                yield sess

        app.dependency_overrides[get_postgres_session] = _override_session
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        app.dependency_overrides.clear()


def _seed_user(session_factory, email: str):
    from src.infrastructure.postgres.repositories.user_repository import UserRepository

    holder = {}

    async def _run():
        async with session_factory() as sess:
            repo = UserRepository(sess)
            user = await repo.create(email=email, name="Switch User")
            await sess.commit()
            holder["id"] = user.id
            holder["email"] = user.email

    asyncio.get_event_loop().run_until_complete(_run())
    token = get_jwt_service().create_access_token(holder["id"], holder["email"])
    return holder, token


class TestIntegrationsOverApi:
    def test_me_defaults_to_both_enabled(self, client, session_factory):
        _, token = _seed_user(session_factory, "switch-default@example.com")
        body = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        ).json()["data"]
        assert body["mcp_enabled"] is True
        assert body["http_api_enabled"] is True

    def test_patch_turns_one_switch_off(self, client, session_factory):
        _, token = _seed_user(session_factory, "switch-off@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        patched = client.patch(
            "/api/v1/auth/me", json={"mcp_enabled": False}, headers=headers
        )
        assert patched.status_code == 200
        assert patched.json()["data"]["mcp_enabled"] is False
        assert patched.json()["data"]["http_api_enabled"] is True

        # ...and it survives the round trip rather than living in the response only.
        body = client.get("/api/v1/auth/me", headers=headers).json()["data"]
        assert body["mcp_enabled"] is False

    def test_a_switch_can_be_turned_off_and_on_again(self, client, session_factory):
        """Not just the first write. See the nested-dict note in integrations.py."""
        _, token = _seed_user(session_factory, "switch-twice@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        client.patch("/api/v1/auth/me", json={"mcp_enabled": False}, headers=headers)
        assert (
            client.get("/api/v1/auth/me", headers=headers).json()["data"]["mcp_enabled"]
            is False
        )

        client.patch("/api/v1/auth/me", json={"mcp_enabled": True}, headers=headers)
        assert (
            client.get("/api/v1/auth/me", headers=headers).json()["data"]["mcp_enabled"]
            is True
        )

    def test_patching_profile_leaves_switches_alone(self, client, session_factory):
        _, token = _seed_user(session_factory, "switch-untouched@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        client.patch("/api/v1/auth/me", json={"http_api_enabled": False}, headers=headers)
        body = client.patch(
            "/api/v1/auth/me", json={"display_name": "Ada"}, headers=headers
        ).json()["data"]

        assert body["display_name"] == "Ada"
        assert body["http_api_enabled"] is False


# -- enforcement --


class TestMcpEnforcement:
    async def test_disabled_mcp_key_is_rejected(self, session_factory):
        """A working key on an account with MCP switched off gets 403, not 401."""
        from src.infrastructure.postgres.repositories.user_repository import UserRepository
        from src.mcp.auth import McpApiKeyAuthMiddleware
        from src.services.auth.api_key_service import ApiKeyService

        holder = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                user = await repo.create(email="mcp-off@test.local", name="MCP Off")
                await repo.update(user, metadata=apply_integration({}, MCP, False))
                svc = ApiKeyService(sess)
                raw_key, _ = await svc.create_key(user.id, "mcp-off-key")
                await sess.commit()
                holder["key"] = raw_key

        await _seed()

        inner_app = AsyncMock()
        middleware = McpApiKeyAuthMiddleware(inner_app)
        sent = []

        async def send(message):
            sent.append(message)

        auth_header = "Bearer " + holder["key"]
        with patch(f"{DB_MODULE}.AsyncSessionLocal", new=session_factory):
            await middleware(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/mcp",
                    "headers": [[b"authorization", auth_header.encode()]],
                },
                AsyncMock(),
                send,
            )

        assert sent[0]["status"] == 403
        inner_app.assert_not_called()


class TestHttpApiEnforcement:
    async def test_api_key_caller_is_blocked_when_switched_off(self):
        """The gate refuses sk- callers..."""
        from src.api.shared.exceptions import ForbiddenException
        from src.core.dependencies import AuthContext, get_http_api_context

        user = _FakeUser(apply_integration({}, HTTP_API, False))
        with pytest.raises(ForbiddenException):
            await get_http_api_context(AuthContext(user=user, api_key_hash="hash"))

    async def test_browser_session_still_passes(self):
        """...and lets the web UI's own JWT-authenticated chat through."""
        from src.core.dependencies import AuthContext, get_http_api_context

        user = _FakeUser(apply_integration({}, HTTP_API, False))
        auth = AuthContext(user=user, api_key_hash=None)
        assert await get_http_api_context(auth) is auth
