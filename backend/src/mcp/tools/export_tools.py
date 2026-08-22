"""MCP tools for Petri Net optimization and PNML export."""

from mcp.server.fastmcp import FastMCP


def register_export_tools(mcp: FastMCP) -> None:
    """Register export and optimization tools on the MCP server."""
    from src.mcp.tools.petri_tools import EXPORT_TOOL_NAMES, register_catalog_tools

    register_catalog_tools(mcp, EXPORT_TOOL_NAMES)
