"""MCP tools for Petri Net simulation."""

from mcp.server.fastmcp import FastMCP


def register_simulation_tools(mcp: FastMCP) -> None:
    """Register simulation tools on the MCP server."""
    from src.mcp.tools.petri_tools import SIMULATION_TOOL_NAMES, register_catalog_tools

    register_catalog_tools(mcp, SIMULATION_TOOL_NAMES)
