"""MCP (Model Context Protocol) server for Petri Net Sim."""


def create_mcp_server():
    """Create and configure the MCP server. Lazy import to avoid circular deps."""
    from .server import create_mcp_server as _create

    return _create()


__all__ = ["create_mcp_server"]
