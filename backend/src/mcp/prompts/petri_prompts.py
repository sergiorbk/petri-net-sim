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

    @mcp.prompt()
    def review_petri_model(task: str = "") -> str:
        """Review a portable training archive and append exact-version evidence."""
        from petri_modeling_skills import read_resource
        return read_resource("petri://skills/petri-training-review") + "\n\n" + modeling_prompt() + "\n\nReview task:\n" + task
