"""Tests for the standalone MCP entrypoint's auth wiring (D3).

backend/mcp_server.py is a top-level script, not a package under src/, but
it is importable as a plain module (`import mcp_server`) the same way
tests/test_health.py already does `from main import app` -- pytest's
rootdir insertion puts backend/ on sys.path.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import mcp_server
from src.mcp.auth import McpApiKeyAuthMiddleware


class TestStreamableHttpAuthWrapping:
    def test_streamable_http_app_is_wrapped_with_auth_middleware(self):
        app = mcp_server._build_authenticated_streamable_http_app()
        middleware_classes = [m.cls for m in app.user_middleware]
        assert McpApiKeyAuthMiddleware in middleware_classes

    def test_bare_streamable_http_app_has_no_auth_middleware(self):
        """Confirms the middleware is genuinely added by our wrapper, not
        already present on the app FastMCP builds -- i.e. this test would
        fail if create_mcp_app_for_mount's wrapping leaked in unexpectedly
        or if streamable_http_app() started adding auth on its own."""
        bare_app = mcp_server.mcp.streamable_http_app()
        middleware_classes = [m.cls for m in bare_app.user_middleware]
        assert McpApiKeyAuthMiddleware not in middleware_classes

    def test_uses_the_standalone_mcp_host_and_port(self):
        """The standalone entrypoint must keep serving on MCP_HOST/MCP_PORT
        (create_mcp_server's settings), not silently switch to the
        FastAPI-mount host/port from create_mcp_app_for_mount."""
        from src.core.config import settings

        assert mcp_server.mcp.settings.host == settings.MCP_HOST
        assert mcp_server.mcp.settings.port == settings.MCP_PORT


class TestMainDispatch:
    """D3: --stdio must never take the auth-wrapping path; the default
    (no --stdio) must always go through it."""

    def test_stdio_flag_runs_stdio_transport_only(self, monkeypatch):
        monkeypatch.setattr(mcp_server.mcp, "run", MagicMock())
        monkeypatch.setattr(mcp_server, "_run_streamable_http_with_auth", MagicMock())

        mcp_server.main(["mcp_server.py", "--stdio"])

        mcp_server.mcp.run.assert_called_once_with(transport="stdio")
        mcp_server._run_streamable_http_with_auth.assert_not_called()

    def test_no_stdio_flag_runs_authenticated_http(self, monkeypatch):
        monkeypatch.setattr(mcp_server.mcp, "run", MagicMock())
        monkeypatch.setattr(mcp_server, "_run_streamable_http_with_auth", MagicMock())

        mcp_server.main(["mcp_server.py"])

        mcp_server._run_streamable_http_with_auth.assert_called_once()
        mcp_server.mcp.run.assert_not_called()


class TestModuleDocstringDocumentsAuthSplit:
    def test_docstring_mentions_auth_for_http_and_authless_stdio(self):
        doc = mcp_server.__doc__ or ""
        assert "McpApiKeyAuthMiddleware" in doc
        assert "stdio" in doc
        assert "authless" in doc.lower()
