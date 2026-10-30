"""MCP resources registration."""

from mcp.server.fastmcp import FastMCP


def register_resources(mcp: FastMCP) -> None:
    """Register all MCP resources."""
    from .pnml_resource import register_pnml_resources

    from .modeling_resources import register_modeling_resources

    register_pnml_resources(mcp)
    register_modeling_resources(mcp)
