"""MCP prompts registration."""

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register all MCP prompts."""
    from .petri_prompts import register_petri_prompts

    register_petri_prompts(mcp)
