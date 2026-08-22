"""
Standalone MCP server entrypoint for Petri Net Sim.

Usage:
    # Streamable HTTP (web clients, MCP Inspector):
    uv run python mcp_server.py

    # stdio (desktop MCP clients):
    uv run python mcp_server.py --stdio

    # Development with MCP Inspector:
    uv run mcp dev mcp_server.py

Auth (D3): streamable-http mode is served behind the same
McpApiKeyAuthMiddleware the FastAPI-mounted MCP endpoint uses (see
src/mcp/server.py's create_mcp_app_for_mount) -- every request needs a
valid `Authorization: Bearer sk-...` API key. stdio mode is NOT wrapped
with this middleware: it is a local, one-to-one pipe between this process
and a locally spawned MCP client (Claude Desktop, `mcp dev`, etc.) with no
network listener to protect, so it stays authless by nature, matching
FastMCP's own stdio transport convention.
"""

import sys

from src.mcp.server import create_mcp_server

mcp = create_mcp_server()


def _build_authenticated_streamable_http_app():
    """Build the streamable-HTTP ASGI app wrapped with McpApiKeyAuthMiddleware (D3).

    `mcp.run(transport="streamable-http")` would serve the bare app FastMCP
    builds internally -- no auth layer at all. That is fine for
    create_mcp_app_for_mount, which is only ever reached by being mounted
    inside the FastAPI app (whose own middleware/routing wraps it), but
    wrong here: this standalone entrypoint has no outer app to do that
    wrapping, so it builds the same kind of authenticated app by hand.
    Split out from _run_streamable_http_with_auth so tests can inspect the
    wrapped app without starting a real uvicorn server.
    """
    from src.mcp.auth import McpApiKeyAuthMiddleware

    app = mcp.streamable_http_app()
    app.add_middleware(McpApiKeyAuthMiddleware)
    return app


def _run_streamable_http_with_auth() -> None:
    """Serve `mcp` over streamable-HTTP behind McpApiKeyAuthMiddleware (D3).

    Uses the same host/port/log_level FastMCP.run() would have used for
    this transport.
    """
    import uvicorn

    app = _build_authenticated_streamable_http_app()
    uvicorn.run(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )


def main(argv: list[str]) -> None:
    """Dispatch to stdio (authless) or streamable-HTTP (authenticated), per D3.

    Split out from the `__main__` guard so tests can exercise the dispatch
    logic itself (which branch calls what) without actually starting a
    server.
    """
    if "--stdio" in argv:
        mcp.run(transport="stdio")
    else:
        _run_streamable_http_with_auth()


if __name__ == "__main__":
    main(sys.argv)
