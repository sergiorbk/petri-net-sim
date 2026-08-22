"""MCP authentication middleware.

Validates API keys (Bearer sk-...) on HTTP transport.
Stdio transport (a local MCP client) is trusted and skips auth.
"""

import json
import logging

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from src.services.auth.integrations import MCP, integration_enabled

logger = logging.getLogger("mcp.auth")


class McpApiKeyAuthMiddleware:
    """ASGI middleware that validates API keys for MCP HTTP transport.

    Extracts ``Authorization: Bearer sk-...`` and validates via ApiKeyService.
    Rejects with 401 if missing/invalid.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        # Only enforce auth on MCP endpoints — pass through everything else
        from src.core.config import settings
        if not request.url.path.startswith(settings.MCP_PATH):
            await self.app(scope, receive, send)
            return

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            await self._reject(send, "Missing Authorization header")
            return

        token = auth_header[7:]  # strip "Bearer "

        if not token.startswith("sk-"):
            await self._reject(send, "Invalid API key format")
            return

        # Validate the key against the database
        from src.infrastructure.postgres.database import AsyncSessionLocal
        from src.services.auth.api_key_service import ApiKeyService

        # Both the key check and the owner's switch are read inside the
        # session: result.user is an ORM row, and reading its metadata after
        # the session closes is a detached-instance risk, not a plain
        # attribute access.
        async with AsyncSessionLocal() as session:
            service = ApiKeyService(session)
            result = await service.authenticate(token)
            mcp_allowed = result is not None and integration_enabled(result.user, MCP)
            user_email = result.user.email if result else None
            key_id = result.key_id if result else None

        if result is None:
            await self._reject(send, "Invalid or revoked API key")
            return

        # A valid key is not, by itself, permission to be here: the owner can
        # close this door from Settings and leave their keys working
        # everywhere else. 403, not 401 -- retrying with another key is not
        # the fix, and telling the caller otherwise invites a key hunt.
        if not mcp_allowed:
            await self._reject(
                send,
                "MCP access is disabled for this account. Enable it in Settings > MCP.",
                status=403,
            )
            return

        logger.debug("MCP auth OK: user=%s key=%s", user_email, key_id)
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send, detail: str, status: int = 401) -> None:
        body = json.dumps({"error": detail}).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode()],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })
