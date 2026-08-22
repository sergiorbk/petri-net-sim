"""Tests against the REAL FastMCP server (contract C1 + E).

Unlike test_mcp_petri_tools.py (which drives a MockFastMCP double),
these tests build the actual `mcp.server.fastmcp.FastMCP` instance via
create_mcp_server() and inspect what it reports through the real MCP
protocol surface: `list_tools()`'s name list and each tool's actual
generated JSON input schema. This is the layer that would catch a
registration-time crash, a silently dropped tool, or a schema FastMCP
itself failed to build from our ToolSpec/Signature plumbing -- none of
which a MockFastMCP-based test can see.
"""

from __future__ import annotations

import pytest

from src.mcp.server import create_mcp_server
from src.services.petri.agent_toolkit import build_catalog

# The full expected tool name list (contract C1: "assert the full expected
# name list in a test"). Hardcoded rather than derived from build_catalog()
# so this test also catches accidental catalog drift, not just a broken
# registration pipeline reflecting the catalog back at itself.
EXPECTED_TOOL_NAMES = frozenset({
    "add_arc", "add_assembly", "add_balking_queue", "add_batch",
    "add_blocking_machine", "add_bounded_queue", "add_breakdown",
    "add_buffer", "add_controller", "add_conveyor", "add_conveyor_line",
    "add_conveyor_workstation", "add_duplicate", "add_feedback_loop",
    "add_finite_population_queue", "add_fork_join", "add_generator",
    "add_machine", "add_merge", "add_multi_resource",
    "add_nonstationary_generator", "add_place", "add_preemptive_machine",
    "add_priority_choice", "add_quality_check", "add_reneging_queue",
    "add_resource_set", "add_retrial_queue", "add_router",
    "add_scheduled_availability", "add_server_vacation", "add_setup_machine",
    "add_terminator", "add_threshold_activation", "add_timed_batch",
    "add_transition", "add_transport_agent", "add_unbatch",
    "add_wip_controller", "arrange_patterns", "auto_layout",
    "connect_blocking_consumer", "connect_bounded_consumer",
    "connect_patterns", "connect_return_loop", "connect_schedule_gate",
    "connect_wip_return", "connect_workstation_bypass", "create_network",
    "create_object", "export_pnml", "find_elements", "find_free_position",
    "get_network_bounds", "get_network_status", "get_pattern_bounds",
    "get_simulation_results", "import_pnml", "link_objects", "list_elements",
    "list_links", "list_objects", "list_pattern_instances",
    "modify_arc", "modify_place", "modify_transition", "move_elements_by",
    "move_elements_to_object", "optimize_network", "remove_arc",
    "remove_link", "remove_object", "remove_place", "remove_transition",
    "rename_object", "run_simulation", "set_active_object",
    "set_layout_direction", "set_positions", "validate_model",
    "validate_net",
})


async def _real_tools() -> dict:
    """Build the real FastMCP server and return {tool_name: Tool}."""
    mcp = create_mcp_server()
    tools = await mcp.list_tools()
    return {t.name: t for t in tools}


class TestRealMcpServerToolNames:
    @pytest.mark.anyio
    async def test_registered_tool_names_match_expected_list(self):
        tools = await _real_tools()
        assert set(tools) == EXPECTED_TOOL_NAMES

    @pytest.mark.anyio
    async def test_registered_tool_names_match_catalog_exactly(self):
        """No tool is silently dropped, duplicated, or renamed between the
        catalog and what FastMCP actually ends up serving."""
        tools = await _real_tools()
        assert set(tools) == frozenset(build_catalog())

    @pytest.mark.anyio
    async def test_tool_count(self):
        tools = await _real_tools()
        assert len(tools) == 81


class TestRepresentativeToolSchemas:
    """E: for a representative sample, the actual generated JSON input
    schema -- params present with their defaults, exactly as a real MCP
    client would see them."""

    @pytest.mark.anyio
    async def test_add_buffer_schema(self):
        tools = await _real_tools()
        schema = tools["add_buffer"].inputSchema
        props = schema["properties"]

        assert set(schema["required"]) == {"name"}
        assert props["name"]["type"] == "string"
        assert props["initial_tokens"]["default"] == 0
        assert props["initial_tokens"]["type"] == "integer"
        assert "capacity" in props  # optional int | None, default null

    @pytest.mark.anyio
    async def test_add_buffer_description_includes_merged_args(self):
        """A2: the class docstring's prose and apply()'s per-parameter Args
        both make it through to the real, client-visible tool description."""
        tools = await _real_tools()
        description = tools["add_buffer"].description
        assert "Buffer" in description
        assert "Args:" in description
        assert "initial_tokens" in description
        assert "capacity" in description

    @pytest.mark.anyio
    async def test_add_quality_check_schema(self):
        tools = await _real_tools()
        schema = tools["add_quality_check"].inputSchema
        props = schema["properties"]

        assert set(schema["required"]) == {"name"}
        assert props["inspection_time"]["default"] == 1.0
        assert props["distribution"]["default"] == "det"
        assert props["distribution"]["type"] == "string"
        assert props["pass_probability"]["default"] == 0.9
        assert props["pass_name"]["default"] == "Passed"
        assert props["fail_name"]["default"] == "Failed"
        assert props["time_unit"]["default"] == "s"

    @pytest.mark.anyio
    async def test_add_generator_schema(self):
        tools = await _real_tools()
        schema = tools["add_generator"].inputSchema
        props = schema["properties"]

        assert set(schema["required"]) == {"name"}
        assert "interval" in props
        assert "rate" in props
        assert props["distribution"]["default"] == "exp"
        assert props["standard_deviation"]["default"] == 0.0
        assert props["batch_size"]["default"] == 1
        assert props["batch_size"]["type"] == "integer"
        assert props["time_unit"]["default"] == "s"
        assert "deviation_unit" in props

    @pytest.mark.anyio
    async def test_add_machine_schema(self):
        tools = await _real_tools()
        schema = tools["add_machine"].inputSchema
        props = schema["properties"]

        assert set(schema["required"]) == {"name", "processing_time"}
        assert props["processing_time"]["type"] == "number"
        assert props["channels"]["default"] == 1
        assert props["distribution"]["default"] == "exp"
        assert props["standard_deviation"]["default"] == 0.0
        assert props["auto_connect"]["default"] is True
        assert props["auto_connect"]["type"] == "boolean"
        assert props["time_unit"]["default"] == "s"
        assert "deviation_unit" in props

    @pytest.mark.anyio
    async def test_import_pnml_schema(self):
        tools = await _real_tools()
        schema = tools["import_pnml"].inputSchema
        props = schema["properties"]

        assert set(schema["required"]) == {"xml"}
        assert props["xml"]["type"] == "string"
        assert props["replace"]["type"] == "boolean"
        assert props["replace"]["default"] is True


class TestChoicesNarrowingOnTheRealSchema:
    """C4: distribution/time_unit (and every other former Literal) come
    back as a real JSON-schema enum on the actual FastMCP-generated input
    schema, not just as a plain "string" type -- exercised end to end
    through create_mcp_server(), not just against the catalog's ToolParam.
    """

    @pytest.mark.anyio
    async def test_add_generator_distribution_enum(self):
        tools = await _real_tools()
        props = tools["add_generator"].inputSchema["properties"]
        assert props["distribution"]["enum"] == ["exp", "norm", "unif", "det"]
        assert props["distribution"]["type"] == "string"

    @pytest.mark.anyio
    async def test_add_generator_time_unit_enum(self):
        tools = await _real_tools()
        props = tools["add_generator"].inputSchema["properties"]
        assert props["time_unit"]["enum"] == ["s", "min", "h", "d"]
        assert props["time_unit"]["type"] == "string"

    @pytest.mark.anyio
    async def test_add_generator_deviation_unit_enum_is_nullable(self):
        tools = await _real_tools()
        props = tools["add_generator"].inputSchema["properties"]
        deviation_unit = props["deviation_unit"]
        # Optional[Literal[...]] renders as an anyOf with the enum branch
        # plus a null branch, rather than a bare "type"/"enum" pair.
        variants = deviation_unit.get("anyOf", [deviation_unit])
        enum_variant = next(v for v in variants if "enum" in v)
        assert enum_variant["enum"] == ["s", "min", "h", "d"]

    @pytest.mark.anyio
    async def test_add_router_strategy_enum(self):
        tools = await _real_tools()
        props = tools["add_router"].inputSchema["properties"]
        assert props["strategy"]["enum"] == ["probability", "priority"]
