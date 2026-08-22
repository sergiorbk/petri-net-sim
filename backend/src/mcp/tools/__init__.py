"""MCP tools registration."""

from mcp.server.fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register all MCP tools."""
    from .export_tools import register_export_tools
    from .petri_tools import register_petri_tools
    from .simulation_tools import register_simulation_tools

    register_petri_tools(mcp)
    register_export_tools(mcp)
    register_simulation_tools(mcp)
