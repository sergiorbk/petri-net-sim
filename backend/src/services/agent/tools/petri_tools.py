"""Petri Net building tools for the chat agent.

Every tool the LLM can call, except create_network and show_chart, whose
behavior doesn't fit the generic shape, is generated straight from the
shared agent_toolkit catalog (src/services/petri/agent_toolkit/catalog.py):
one ToolSpec in, one StructuredTool out. There is no more hand-written
per-pattern function here and no per-tool time-unit conversion; the catalog
is the single source of truth for names, descriptions, and parameter
schemas, matching what backend/src/mcp/tools/* registers for the same
tools. Distribution/RoutingStrategy/etc Literal narrowing is restored via
each ToolSpec's per-param `choices` and `effective_type()` (see catalog.py)
rather than hand-written `Literal[...]` annotations.

These wrappers are schema-only: the LLM only ever sees their name,
description, and args_schema (bind_tools() never calls their python body;
tool_node.py intercepts the raw tool_calls off the AIMessage and dispatches
straight into the catalog's operation). Each wrapper's body still returns
the historical `{"_tool_action": <name>, **kwargs}` dict, unconverted,
raw kwargs exactly as the LLM supplied them, so the contract that shape
represents stays intact for anything that does call `.invoke()` directly
(e.g. tests), and so tool_node's dispatch can rely on tool_call["args"]
carrying the same un-normalized values a direct `.invoke()` would produce.
Time-unit conversion now happens exactly once, inside each op_* function
in operations.py, driven by the raw time_unit/deviation_unit args tool_node
forwards unchanged.
"""

import json
from typing import Any, Literal

from langchain_core.tools import StructuredTool, tool
from pydantic import Field, create_model

from src.domain import PetriNet
from src.services.petri.agent_toolkit.catalog import ToolSpec, build_catalog, effective_type

# ---------------------------------------------------------------------------
# Special cases: these two tools don't fit the generic catalog shape.
# ---------------------------------------------------------------------------


@tool
def create_network(name: str = "PetriNet") -> dict:
    """
    Create a new empty Petri Net, clearing any previous network.

    Use this FIRST when user wants to build a new model from scratch.

    Args:
        name: Name for the new network (default: "PetriNet")

    Returns:
        Confirmation message and empty network data
    """
    net = PetriNet(name=name)
    return {
        "status": "success",
        "message": f"Created new empty network '{name}'",
        "net_data": net.model_dump(),
    }


@tool
def show_chart(
    chart_type: Literal["bar", "line", "pie"],
    title: str,
    data_json: str,
    x_key: str = "name",
    y_key: str = "value",
) -> dict:
    """
    Display a chart/graph inline in the chat. The frontend renders it visually.

    ALWAYS use this tool instead of ASCII art, text-based charts, or code snippets.

    Args:
        chart_type: Type of chart - "bar", "line", or "pie"
        title: Chart title
        data_json: JSON string of data points array.
                   Example: '[{"name": "p1", "value": 100}, {"name": "p2", "value": 200}]'
        x_key: Key for X axis / category name (default: "name")
        y_key: Key for Y axis / numeric value (default: "value")

    Returns:
        Confirmation that chart was rendered

    Examples:
        - Bar chart: show_chart("bar", "Token Distribution",
            '[{"name": "p1", "value": 5}, {"name": "p2", "value": 3}]')
        - Pie chart: show_chart("pie", "Branch Distribution",
            '[{"name": "Upper", "value": 42}, {"name": "Lower", "value": 58}]')
    """
    data = json.loads(data_json) if isinstance(data_json, str) else data_json
    return {
        "_chart": json.dumps({
            "type": chart_type,
            "title": title,
            "data": data,
            "xKey": x_key,
            "yKey": y_key,
        }),
    }


#: Catalog entries that stay off the generated list: create_network keeps
#: its own hand-written schema/return shape above (its op_create_network
#: counterpart is still used by other adapters, e.g. MCP); show_chart isn't
#: in the catalog at all, since it never touches a PetriNetSession.
_SPECIAL_CASE_NAMES = frozenset({"create_network"})


# ---------------------------------------------------------------------------
# Generic catalog -> StructuredTool
# ---------------------------------------------------------------------------


def _make_catalog_tool(spec: ToolSpec) -> StructuredTool:
    """Build one schema-only StructuredTool from a catalog ToolSpec.

    The generated function never touches a PetriNetSession or spec.operation
    -- it only packages its kwargs into the `_tool_action` dict tool_node
    reads back off the AIMessage's tool_calls. args_schema is built directly
    from spec.params, so a parameter gained by the catalog (e.g. A1's
    previously-swallowed pattern kwargs) is gained here too, automatically.
    """
    fields: dict[str, Any] = {}
    for p in spec.params:
        ptype = effective_type(p)
        if p.required:
            fields[p.name] = (ptype, Field(description=p.description))
        else:
            fields[p.name] = (ptype, Field(default=p.default, description=p.description))

    input_model = create_model(f"{spec.name.title().replace('_', '')}Input", **fields)

    def _impl(**kwargs: Any) -> dict:
        return {"_tool_action": spec.name, **kwargs}

    return StructuredTool.from_function(
        func=_impl,
        name=spec.name,
        description=spec.description,
        args_schema=input_model,
    )


def _build_petri_tools() -> list:
    """Assemble the full LLM-facing tool list: special cases + catalog."""
    catalog = build_catalog()
    generated = [
        _make_catalog_tool(spec)
        for name, spec in catalog.items()
        if name not in _SPECIAL_CASE_NAMES
    ]
    return [create_network, *generated, show_chart]


PETRI_TOOLS = _build_petri_tools()
