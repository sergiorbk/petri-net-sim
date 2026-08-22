"""Shared core for every agent-facing Petri Net tool surface.

This package holds the ONE implementation of tool behavior that the MCP
server, the in-app chat agent, and any future tool_node-style dispatcher
all call into. It deliberately imports neither FastMCP nor langchain;
those belong to the thin adapters in backend/src/mcp/ and
backend/src/services/agent/, which translate this package's plain
str | ToolError results into their own protocol's tool-result shape.
"""

from src.services.petri.agent_toolkit.errors import ToolError, tool_operation
from src.services.petri.agent_toolkit.catalog import (
    ToolParam,
    ToolSpec,
    build_catalog,
    effective_type,
)

__all__ = [
    "ToolError",
    "tool_operation",
    "ToolParam",
    "ToolSpec",
    "build_catalog",
    "effective_type",
]
