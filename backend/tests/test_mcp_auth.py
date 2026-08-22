"""Tests for MCP auth middleware."""

import pytest
from unittest.mock import AsyncMock, patch

from src.mcp.auth import McpApiKeyAuthMiddleware


class TestMcpApiKeyAuthMiddleware:
    """Test the ASGI middleware for MCP API key authentication."""

    @pytest.fixture
    def inner_app(self):
        """Mock ASGI app that records calls."""
        app = AsyncMock()
        return app

    @pytest.fixture
    def middleware(self, inner_app):
        return McpApiKeyAuthMiddleware(inner_app)

    async def _call_middleware(self, middleware, headers: dict | None = None):
        """Helper to invoke middleware with an HTTP scope and capture response."""
        raw_headers = []
        if headers:
            for k, v in headers.items():
                raw_headers.append([k.lower().encode(), v.encode()])

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": raw_headers,
        }

        sent_messages = []

        async def send(message):
            sent_messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b""}

        await middleware(scope, receive, send)
        return sent_messages

    async def test_non_http_scope_passes_through(self, middleware, inner_app):
        """Non-HTTP scopes (lifespan, websocket) pass through without auth."""
        scope = {"type": "lifespan"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        inner_app.assert_called_once_with(scope, receive, send)

    async def test_missing_auth_header_returns_401(self, middleware, inner_app):
        sent = await self._call_middleware(middleware)
        assert sent[0]["status"] == 401
        inner_app.assert_not_called()

    async def test_non_bearer_auth_returns_401(self, middleware, inner_app):
        sent = await self._call_middleware(middleware, {"authorization": "Basic abc123"})
        assert sent[0]["status"] == 401
        inner_app.assert_not_called()

    async def test_non_sk_token_returns_401(self, middleware, inner_app):
        sent = await self._call_middleware(middleware, {"authorization": "Bearer jwt-token-here"})
        assert sent[0]["status"] == 401
        inner_app.assert_not_called()

    async def test_invalid_api_key_returns_401(self, middleware, inner_app, session_factory):
        with patch("src.infrastructure.postgres.database.AsyncSessionLocal", new=session_factory):
            sent = await self._call_middleware(
                middleware, {"authorization": "Bearer sk-nonexistent12345"}
            )
        assert sent[0]["status"] == 401
        inner_app.assert_not_called()

    async def test_valid_api_key_passes_through(self, middleware, inner_app, session_factory):
        """Valid API key allows request to pass to the inner app."""
        import asyncio
        from src.infrastructure.postgres.repositories.user_repository import UserRepository
        from src.services.auth.api_key_service import ApiKeyService

        raw_key_holder = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                u = await repo.create(email="mcp@test.local", name="MCP User")
                svc = ApiKeyService(sess)
                raw_key, _ = await svc.create_key(u.id, "mcp-key")
                await sess.commit()
                raw_key_holder["key"] = raw_key

        await _seed()

        with patch("src.infrastructure.postgres.database.AsyncSessionLocal", new=session_factory):
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [
                    [b"authorization", f"Bearer {raw_key_holder['key']}".encode()],
                ],
            }
            receive = AsyncMock()
            send = AsyncMock()
            await middleware(scope, receive, send)

        inner_app.assert_called_once()

    async def test_revoked_key_returns_401(self, middleware, inner_app, session_factory):
        """Revoked API key is rejected."""
        from src.infrastructure.postgres.repositories.user_repository import UserRepository
        from src.services.auth.api_key_service import ApiKeyService

        raw_key_holder = {}

        async def _seed():
            async with session_factory() as sess:
                repo = UserRepository(sess)
                u = await repo.create(email="revoked-mcp@test.local", name="Revoked")
                svc = ApiKeyService(sess)
                raw_key, key_id = await svc.create_key(u.id, "revoked-key")
                await svc.revoke_key(key_id, u.id)
                await sess.commit()
                raw_key_holder["key"] = raw_key

        await _seed()

        with patch("src.infrastructure.postgres.database.AsyncSessionLocal", new=session_factory):
            sent = await self._call_middleware(
                middleware, {"authorization": f"Bearer {raw_key_holder['key']}"}
            )
        assert sent[0]["status"] == 401
        inner_app.assert_not_called()
