"""MCP task prompts backed by the shared modeling package."""

from mcp.server.fastmcp import FastMCP

from src.services.modeling_guidance import modeling_prompt


def register_petri_prompts(mcp: FastMCP) -> None:
    @mcp.prompt()
    def build_queueing_system(description: str) -> str:
        """Build a Petri net model from a queueing system description."""
        return f"{modeling_prompt()}\n\nRequested queueing system:\n{description}"

    @mcp.prompt()
    def build_production_line(description: str) -> str:
        """Build a Petri net model for a production/manufacturing line."""
        return f"{modeling_prompt()}\n\nRequested production line:\n{description}"

    @mcp.prompt()
    def reconstruct_petri_net(description: str) -> str:
        """Reconstruct a Petri model from an image supplied by the client."""
        return f"{modeling_prompt()}\n\nClient image reconstruction task:\n{description}"
