"""Tests for the chat agent's petri_tools module.

Every tool except create_network and show_chart is now generated straight
from the shared agent_toolkit catalog (see src/services/agent/tools/
petri_tools.py's own module docstring): a schema-only StructuredTool whose
body just packages its raw, unconverted kwargs into the historical
`{"_tool_action": <name>, **kwargs}` dict. There is no more hand-written
time-unit conversion here -- that now happens exactly once, inside the
op_* function tool_node.py dispatches to (see test_agent_tool_node.py and
test_time_unit_handling.py for the end-to-end conversion behavior).
"""

from __future__ import annotations

import json

import pytest

from src.services.agent.tools.petri_tools import PETRI_TOOLS, create_network, show_chart
from src.services.petri.agent_toolkit.catalog import build_catalog

_TOOLS_BY_NAME = {t.name: t for t in PETRI_TOOLS}


class TestCreateNetwork:
    """create_network is hand-written: it returns net_data directly, not
    the {"_tool_action": ...} dict, and it isn't in the catalog at all."""

    def test_returns_net_data(self):
        result = create_network.invoke({"name": "TestNet"})
        assert result["status"] == "success"
        assert "TestNet" in result["message"]
        assert "net_data" in result

    def test_default_name(self):
        result = create_network.invoke({"name": "PetriNet"})
        assert result["status"] == "success"
        assert "net_data" in result

    def test_not_in_catalog(self):
        # create_network's catalog counterpart (op_create_network) exists for
        # other adapters (MCP), but the chat wrapper deliberately stays
        # hand-written -- see petri_tools.py's _SPECIAL_CASE_NAMES.
        assert "create_network" in build_catalog()
        assert _TOOLS_BY_NAME["create_network"] is create_network


class TestShowChart:
    """show_chart never touches a PetriNetSession, so it isn't a catalog
    entry at all -- it's entirely hand-written, same as before."""

    def test_bar_chart(self):
        result = show_chart.invoke({
            "chart_type": "bar",
            "title": "Tokens",
            "data_json": '[{"name": "p1", "value": 5}]',
        })
        chart = json.loads(result["_chart"])
        assert chart["type"] == "bar"
        assert chart["title"] == "Tokens"

    def test_pie_chart(self):
        result = show_chart.invoke({
            "chart_type": "pie",
            "title": "Distribution",
            "data_json": '[{"name": "A", "value": 60}, {"name": "B", "value": 40}]',
        })
        chart = json.loads(result["_chart"])
        assert chart["type"] == "pie"
        assert len(chart["data"]) == 2

    def test_not_in_catalog(self):
        assert "show_chart" not in build_catalog()


class TestGeneratedToolList:
    """PETRI_TOOLS is generated from build_catalog(); these pin that
    contract rather than any individual tool's hand-written body (there
    isn't one any more, except the two special cases above)."""

    def test_covers_every_catalog_tool_except_create_network(self):
        catalog_names = set(build_catalog()) - {"create_network"}
        assert catalog_names <= set(_TOOLS_BY_NAME)

    def test_no_duplicate_tool_names(self):
        names = [t.name for t in PETRI_TOOLS]
        assert len(names) == len(set(names))

    def test_generated_tool_count_matches_catalog_plus_show_chart(self):
        # PETRI_TOOLS = catalog (all generated except create_network, which
        # stays hand-written) plus show_chart, which isn't in the catalog
        # at all -- net delta vs len(catalog) is exactly +1 (show_chart).
        assert len(PETRI_TOOLS) == len(build_catalog()) + 1

    def test_every_generated_tool_schema_matches_its_catalog_spec(self):
        """Drift guard: each generated StructuredTool's args_schema field
        names must exactly match its ToolSpec's params -- this is really a
        test of _make_catalog_tool's introspection, not of any one tool."""
        catalog = build_catalog()
        for name, spec in catalog.items():
            if name == "create_network":
                continue
            tool = _TOOLS_BY_NAME[name]
            schema_fields = set(tool.args_schema.model_fields)
            spec_fields = {p.name for p in spec.params}
            assert schema_fields == spec_fields, (
                f"{name}: StructuredTool fields {schema_fields} != "
                f"ToolSpec params {spec_fields}"
            )

    def test_required_fields_match_between_schema_and_spec(self):
        catalog = build_catalog()
        for name, spec in catalog.items():
            if name == "create_network":
                continue
            tool = _TOOLS_BY_NAME[name]
            required_in_schema = {
                pname for pname, field in tool.args_schema.model_fields.items()
                if field.is_required()
            }
            required_in_spec = {p.name for p in spec.params if p.required}
            assert required_in_schema == required_in_spec, (
                f"{name}: required fields {required_in_schema} != "
                f"spec-required {required_in_spec}"
            )


class TestGeneratedToolBodyIsSchemaOnly:
    """A representative sample: invoking a generated tool packages its RAW
    kwargs -- no time-unit conversion, no station-time rewriting, nothing
    the old hand-written bodies used to do. tool_node.py is what actually
    converts, via the op_* function each tool name resolves to."""

    def test_add_generator_passes_time_unit_through_unconverted(self):
        tool = _TOOLS_BY_NAME["add_generator"]
        result = tool.invoke({"name": "Gen1", "interval": 2.0, "time_unit": "min"})
        assert result["_tool_action"] == "add_generator"
        assert result["name"] == "Gen1"
        # Unconverted: the wrapper no longer does _s(2.0, "min") == 120.0.
        assert result["interval"] == 2.0
        assert result["time_unit"] == "min"

    def test_add_machine_defaults_come_through(self):
        tool = _TOOLS_BY_NAME["add_machine"]
        result = tool.invoke({"name": "M1", "processing_time": 10.0})
        assert result["_tool_action"] == "add_machine"
        assert result["processing_time"] == 10.0
        assert result["channels"] == 1
        assert result["distribution"] == "exp"

    def test_run_simulation_time_unit_unconverted(self):
        tool = _TOOLS_BY_NAME["run_simulation"]
        result = tool.invoke({"simulation_time": 1.0, "time_unit": "h"})
        assert result["_tool_action"] == "run_simulation"
        assert result["simulation_time"] == 1.0
        assert result["time_unit"] == "h"

    def test_export_pnml_no_args(self):
        tool = _TOOLS_BY_NAME["export_pnml"]
        result = tool.invoke({})
        assert result["_tool_action"] == "export_pnml"

    def test_import_pnml_forwards_xml_and_replace(self):
        tool = _TOOLS_BY_NAME["import_pnml"]
        result = tool.invoke({"xml": "<pnml/>", "replace": False})
        assert result["_tool_action"] == "import_pnml"
        assert result["xml"] == "<pnml/>"
        assert result["replace"] is False

    def test_import_pnml_replace_defaults_true(self):
        tool = _TOOLS_BY_NAME["import_pnml"]
        result = tool.invoke({"xml": "<pnml/>"})
        assert result["replace"] is True

    def test_connect_patterns_forwards_ids(self):
        tool = _TOOLS_BY_NAME["connect_patterns"]
        result = tool.invoke({"source_output_id": "p1", "target_input_id": "p2"})
        assert result["_tool_action"] == "connect_patterns"
        assert result["source_output_id"] == "p1"
        assert result["target_input_id"] == "p2"

    def test_get_network_status_no_args(self):
        tool = _TOOLS_BY_NAME["get_network_status"]
        result = tool.invoke({})
        assert result["_tool_action"] == "get_network_status"

    def test_pattern_introspected_tool_add_buffer(self):
        """A1-fixed pattern: add_buffer's previously-swallowed kwargs are now
        real, individually-schema'd fields on the generated tool too."""
        tool = _TOOLS_BY_NAME["add_buffer"]
        result = tool.invoke({"name": "Q1", "capacity": 5})
        assert result["_tool_action"] == "add_buffer"
        assert result["capacity"] == 5


class TestChoicesNarrowingOnTheChatSchema:
    """C4: distribution/time_unit (and every other former Literal) come
    back as a real Literal[...] on the generated StructuredTool's Pydantic
    args_schema, not a plain str field with no enum narrowing.
    """

    def test_add_generator_distribution_is_a_literal(self):
        from typing import Literal

        tool = _TOOLS_BY_NAME["add_generator"]
        field = tool.args_schema.model_fields["distribution"]
        assert field.annotation == Literal["exp", "norm", "unif", "det"]
        assert field.default == "exp"

    def test_add_generator_time_unit_is_a_literal(self):
        from typing import Literal

        tool = _TOOLS_BY_NAME["add_generator"]
        field = tool.args_schema.model_fields["time_unit"]
        assert field.annotation == Literal["s", "min", "h", "d"]
        assert field.default == "s"

    def test_add_generator_deviation_unit_literal_allows_none(self):
        tool = _TOOLS_BY_NAME["add_generator"]
        field = tool.args_schema.model_fields["deviation_unit"]
        assert field.default is None
        # Invoking with an omitted deviation_unit must still validate.
        result = tool.invoke({"name": "Gen1", "interval": 1.0})
        assert result["deviation_unit"] is None

    def test_add_generator_rejects_an_invalid_distribution_value(self):
        tool = _TOOLS_BY_NAME["add_generator"]
        with pytest.raises(Exception):
            tool.invoke({"name": "Gen1", "interval": 1.0, "distribution": "not_a_real_one"})

    def test_add_router_strategy_is_a_literal(self):
        from typing import Literal

        tool = _TOOLS_BY_NAME["add_router"]
        field = tool.args_schema.model_fields["strategy"]
        assert field.annotation == Literal["probability", "priority"]
