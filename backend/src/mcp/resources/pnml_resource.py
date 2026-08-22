"""MCP resources for Petri Net data access."""

from mcp.server.fastmcp import Context, FastMCP


def register_pnml_resources(mcp: FastMCP) -> None:
    """Register Petri Net resources on the MCP server."""
    from src.mcp.tools.petri_tools import _get_session

    @mcp.resource("pnml://current")
    async def get_current_pnml(ctx: Context) -> str:
        """Get the current Petri Net as PNML XML.

        Checks `has_any_content` (every object, not just the active one)
        rather than `session.net.places` alone: a composed session whose
        active object (or the free pool) happens to be empty right now
        can still have real content elsewhere, and used to be misreported
        as "No network built yet" by looking only at the active net.
        """
        session = await _get_session(ctx)
        if not session.has_any_content:
            return "No network built yet. Use create_network tool first."
        return session.export_pnml()

    @mcp.resource("petri://status")
    async def get_network_status(ctx: Context) -> str:
        """Get current Petri Net status summary."""
        session = await _get_session(ctx)
        status = session.get_status()
        if status["places"] == 0:
            return "No network built yet."
        return (
            f"Network '{status['name']}': "
            f"{status['places']} places, "
            f"{status['transitions']} transitions, "
            f"{status['arcs']} arcs, "
            f"valid={status['valid']}"
        )
