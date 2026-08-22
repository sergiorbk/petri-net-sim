"""Tests for the real async tool_node() dispatcher (phase-1 contract, E).

Exercises the actual coroutine with hand-built AIMessages, not any of the
individual op_* functions directly (those are covered in
test_agent_toolkit_*.py and test_time_unit_handling.py). Three required
paths, per the contract: success, ToolError -> status="error", and an
unknown tool name.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.services.agent.nodes.tool_node import tool_node


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id}


def _ai_message(*calls: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=list(calls))


def _state(
    message: AIMessage,
    net_data: dict | None = None,
    net_style: str | None = None,
) -> dict:
    state = {
        "messages": [message],
        "net_data": net_data or {},
        "conversation_id": "c1",
    }
    if net_style is not None:
        state["context"] = {"net_style": net_style}
    return state


class TestSuccessPath:
    @pytest.mark.asyncio
    async def test_create_network_then_add_generator(self):
        state = _state(_ai_message(
            _tool_call("create_network", {"name": "Test"}, "t1"),
        ))
        result = await tool_node(state)

        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, ToolMessage)
        assert msg.tool_call_id == "t1"
        assert getattr(msg, "status", "success") == "success"
        assert "Test" in msg.content
        assert result["net_data"]["name"] == "Test"
        assert result["error"] is None
        assert result["next_action"] == "respond"

    @pytest.mark.asyncio
    async def test_add_generator_reaches_the_builder_with_seconds(self):
        """End-to-end proof that spec.operation (not a re-implementation
        here) is what tool_node calls -- time_unit conversion happens
        exactly once, inside op_add_generator."""
        state = _state(_ai_message(
            _tool_call("create_network", {"name": "Net"}, "t1"),
            _tool_call(
                "add_generator",
                {"name": "Gen", "interval": 2.0, "time_unit": "min"},
                "t2",
            ),
        ))
        result = await tool_node(state)

        gen_msg = result["messages"][1]
        assert getattr(gen_msg, "status", "success") == "success"
        transitions = result["net_data"]["transitions"]
        gen = next(t for t in transitions if t["name"] == "Gen_Gen")
        assert gen["mean_delay"] == 120.0

    @pytest.mark.asyncio
    async def test_run_simulation_then_get_simulation_results_same_turn(self):
        """One session spans the whole batch, so a same-turn
        get_simulation_results call sees the run_simulation result the
        session (deliberately) never persists into net_data."""
        state = _state(_ai_message(
            _tool_call("create_network", {"name": "Net"}, "t1"),
            _tool_call("add_generator", {"name": "Gen", "interval": 1.0}, "t2"),
            _tool_call("add_terminator", {"name": "T"}, "t3"),
        ))
        built = await tool_node(state)

        state2 = _state(_ai_message(
            _tool_call("run_simulation", {"simulation_time": 5.0}, "t4"),
            _tool_call("get_simulation_results", {}, "t5"),
        ), net_data=built["net_data"])
        result = await tool_node(state2)

        run_msg, results_msg = result["messages"]
        assert getattr(run_msg, "status", "success") == "success"
        assert getattr(results_msg, "status", "success") == "success"
        assert "No simulation has been run yet" not in results_msg.content
        assert "Simulation completed" in results_msg.content

    @pytest.mark.asyncio
    async def test_show_chart_produces_chart_payload(self):
        state = _state(_ai_message(
            _tool_call(
                "show_chart",
                {
                    "chart_type": "bar",
                    "title": "Tokens",
                    "data_json": json.dumps([{"name": "p1", "value": 5}]),
                },
                "t1",
            ),
        ))
        result = await tool_node(state)
        msg = result["messages"][0]
        assert getattr(msg, "status", "success") == "success"
        payload = json.loads(msg.content)
        assert payload["type"] == "bar"
        assert payload["title"] == "Tokens"

    @pytest.mark.asyncio
    async def test_export_pnml_side_channels_xml_not_content(self):
        """The system prompt tells the LLM never to paste PNML into chat;
        tool_node enforces that by keeping the XML out of the ToolMessage
        content and stashing it on net_data._last_pnml_export instead,
        for openai_chat_service to turn into a download link."""
        built = await tool_node(_state(_ai_message(
            _tool_call("create_network", {"name": "Net"}, "t1"),
            _tool_call("add_generator", {"name": "Gen", "interval": 1.0}, "t2"),
            _tool_call("add_terminator", {"name": "T"}, "t3"),
        )))
        result = await tool_node(_state(
            _ai_message(_tool_call("export_pnml", {}, "t4")),
            net_data=built["net_data"],
        ))
        msg = result["messages"][0]
        assert getattr(msg, "status", "success") == "success"
        assert "<?xml" not in msg.content
        assert "<?xml" in result["net_data"]["_last_pnml_export"]


class TestAutoOptimizeDisabled:
    """C1: tool_node constructs its session with auto_optimize=False, so
    connecting two patterns never silently fuses the Transfer transition
    connect() creates -- unlike the MCP surface, where it always did (and
    still does; see test_mcp_petri_tools.py's mirror of this test).
    """

    @pytest.mark.asyncio
    async def test_transfer_transition_survives_without_explicit_optimize(self):
        state = _state(_ai_message(
            _tool_call("create_network", {"name": "Net"}, "t1"),
            _tool_call("add_generator", {"name": "Gen", "interval": 1.0}, "t2"),
            _tool_call("add_machine", {"name": "M1", "processing_time": 1.0}, "t3"),
        ))
        result = await tool_node(state)

        transitions = result["net_data"]["transitions"]
        assert any(t["name"].startswith("Transfer_") for t in transitions), (
            "chat tool_node must not auto-optimize away the Transfer "
            "transition add_machine's auto-connect creates"
        )
        assert result["net_data"]["_is_optimized"] is False

    async def _built(self, net_style: str) -> dict:
        result = await tool_node(_state(
            _ai_message(
                _tool_call("create_network", {"name": "Net"}, "t1"),
                _tool_call("add_generator", {"name": "Gen", "interval": 1.0}, "t2"),
                _tool_call("add_machine", {"name": "M1", "processing_time": 1.0}, "t3"),
            ),
            net_style=net_style,
        ))
        return await tool_node(_state(
            _ai_message(_tool_call("optimize_network", {}, "t4")),
            net_data=result["net_data"],
            net_style=net_style,
        ))

    @pytest.mark.asyncio
    async def test_optimize_network_still_fuses_transfers_in_classical_mode(self):
        result = await self._built("classical")
        transitions = result["net_data"]["transitions"]
        assert not any(t["name"].startswith("Transfer_") for t in transitions)
        assert result["net_data"]["_is_optimized"] is True

    @pytest.mark.asyncio
    async def test_optimize_network_keeps_pattern_ports_in_object_mode(self):
        """Fusing a Transfer merges the place one pattern hands off from
        with the place the next hands off to. In Object mode that place is
        the boundary between two Petri-objects, and once it is gone the
        model cannot be separated -- so the fusion is refused and the
        connector is dissolved later, into a place-fusion link, by
        PetriNetSession.ensure_patterns_in_objects instead."""
        result = await self._built("object")
        transitions = result["net_data"]["transitions"]
        assert any(t["name"].startswith("Transfer_") for t in transitions)
        assert result["net_data"]["_is_optimized"] is True
        assert {p["name"] for p in result["net_data"]["places"]} >= {
            "Gen_Out", "M1_Queue",
        }


class TestCrossTurnSimulationResults:
    """C2: get_simulation_results in a LATER tool_node invocation than
    run_simulation, with only net_data carried over (no shared session
    instance), still returns the real numbers instead of "no simulation
    has been run yet".
    """

    @pytest.mark.asyncio
    async def test_get_simulation_results_in_a_separate_later_call(self):
        built = await tool_node(_state(_ai_message(
            _tool_call("create_network", {"name": "Net"}, "t1"),
            _tool_call("add_generator", {"name": "Gen", "interval": 1.0}, "t2"),
            _tool_call("add_terminator", {"name": "T"}, "t3"),
        )))
        ran = await tool_node(_state(
            _ai_message(_tool_call("run_simulation", {"simulation_time": 5.0}, "t4")),
            net_data=built["net_data"],
        ))

        # A brand new tool_node call: a fresh PetriNetSession is rehydrated
        # from net_data alone, exactly as it would be for a later chat turn.
        result = await tool_node(_state(
            _ai_message(_tool_call("get_simulation_results", {}, "t5")),
            net_data=ran["net_data"],
        ))

        msg = result["messages"][0]
        assert getattr(msg, "status", "success") == "success"
        assert "No simulation has been run yet" not in msg.content
        assert "Simulation completed" in msg.content


class TestExportNetworkAlias:
    """C6: export_network is a tolerant alias for the unified export_pnml
    tool name, in case an LLM still emits the pre-rename name."""

    @pytest.mark.asyncio
    async def test_export_network_dispatches_to_export_pnml(self):
        built = await tool_node(_state(_ai_message(
            _tool_call("create_network", {"name": "Net"}, "t1"),
            _tool_call("add_generator", {"name": "Gen", "interval": 1.0}, "t2"),
            _tool_call("add_terminator", {"name": "T"}, "t3"),
        )))
        result = await tool_node(_state(
            _ai_message(_tool_call("export_network", {}, "t4")),
            net_data=built["net_data"],
        ))

        msg = result["messages"][0]
        assert getattr(msg, "status", "success") == "success"
        assert msg.name == "export_network"  # echoes the name the LLM used
        assert "<?xml" not in msg.content
        assert "<?xml" in result["net_data"]["_last_pnml_export"]


class TestUnknownKwargFiltering:
    """C5: a hallucinated parameter name is dropped, not a hard TypeError
    naming the internal op_* function."""

    @pytest.mark.asyncio
    async def test_stray_kwarg_on_add_machine_is_ignored(self):
        state = _state(_ai_message(
            _tool_call("create_network", {"name": "Net"}, "t1"),
            _tool_call(
                "add_machine",
                {"name": "M1", "processing_time": 5.0, "bogus_param": 1},
                "t2",
            ),
        ))
        result = await tool_node(state)

        msg = result["messages"][1]
        assert getattr(msg, "status", "success") == "success"
        assert "M1" in msg.content
        assert "Ignored unknown parameter(s): bogus_param" in msg.content


class TestToolErrorPath:
    @pytest.mark.asyncio
    async def test_tool_error_sets_status_error(self):
        """connect_workstation_bypass raises ValueError on an unknown
        workstation name; @tool_operation turns that into a ToolError, and
        tool_node must surface it as ToolMessage(status="error")."""
        state = _state(_ai_message(
            _tool_call(
                "connect_workstation_bypass",
                {"source_workstation_name": "nope", "target_workstation_name": "nope2"},
                "t1",
            ),
        ))
        result = await tool_node(state)

        msg = result["messages"][0]
        assert msg.status == "error"
        assert "nope" in msg.content
        # A ToolError doesn't abort the graph run -- the LLM sees it on its
        # next turn and can react; the top-level error field stays clear.
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_export_pnml_error_status_and_no_side_channel(self):
        """Exporting an empty/disconnected net is a ToolError; the PNML
        side channel must not be populated when the export itself failed."""
        state = _state(_ai_message(
            _tool_call("create_network", {"name": "Net"}, "t1"),
            _tool_call("add_place", {"name": "Orphan"}, "t2"),
            _tool_call("add_place", {"name": "Orphan2"}, "t3"),
            _tool_call("export_pnml", {}, "t4"),
        ))
        result = await tool_node(state)

        export_msg = result["messages"][-1]
        assert export_msg.status == "error"
        assert "_last_pnml_export" not in result["net_data"]


class TestUnknownToolPath:
    @pytest.mark.asyncio
    async def test_unknown_tool_name_reports_error_status(self):
        state = _state(_ai_message(
            _tool_call("this_tool_does_not_exist", {"foo": "bar"}, "t1"),
        ))
        result = await tool_node(state)

        msg = result["messages"][0]
        assert msg.tool_call_id == "t1"
        assert msg.status == "error"
        assert "this_tool_does_not_exist" in msg.content
        assert result["error"] is None
        assert result["next_action"] == "respond"

    @pytest.mark.asyncio
    async def test_unknown_tool_does_not_disturb_net_data(self):
        built = await tool_node(_state(_ai_message(
            _tool_call("create_network", {"name": "Net"}, "t1"),
            _tool_call("add_place", {"name": "P1"}, "t2"),
        )))
        result = await tool_node(_state(
            _ai_message(_tool_call("bogus", {}, "t3")),
            net_data=built["net_data"],
        ))
        assert result["net_data"]["name"] == "Net"
        assert len(result["net_data"]["places"]) == 1


class TestImportPnml:
    """Part B: import_pnml on the chat surface. Registered through the
    same catalog dispatch every other tool goes through (spec.operation
    at line ~139) -- no special-casing like export_pnml's file-download
    side channel, so these exercise tool_node exactly like TestSuccessPath
    above.
    """

    @pytest.mark.asyncio
    async def test_import_replaces_an_empty_session(self):
        from tests.test_pnml_importer import SAMPLE_PNML

        state = _state(_ai_message(
            _tool_call("import_pnml", {"xml": SAMPLE_PNML}, "t1"),
        ))
        result = await tool_node(state)

        msg = result["messages"][0]
        assert getattr(msg, "status", "success") == "success"
        assert "2 place(s)" in msg.content
        assert "1 transition(s)" in msg.content
        assert result["net_data"]["name"] == "Test Net"
        assert len(result["net_data"]["places"]) == 2

    @pytest.mark.asyncio
    async def test_import_refuses_when_replace_false_and_session_non_empty(self):
        from tests.test_pnml_importer import SAMPLE_PNML

        built = await tool_node(_state(_ai_message(
            _tool_call("create_network", {"name": "Existing"}, "t1"),
            _tool_call("add_place", {"name": "Orphan"}, "t2"),
        )))
        result = await tool_node(_state(
            _ai_message(_tool_call(
                "import_pnml", {"xml": SAMPLE_PNML, "replace": False}, "t3",
            )),
            net_data=built["net_data"],
        ))

        msg = result["messages"][0]
        assert msg.status == "error"
        assert "replace" in msg.content.lower()
        # Untouched: the original session's model survives the refusal.
        assert result["net_data"]["name"] == "Existing"
        assert len(result["net_data"]["places"]) == 1

    @pytest.mark.asyncio
    async def test_import_with_replace_true_overwrites_non_empty_session(self):
        from tests.test_pnml_importer import SAMPLE_PNML

        built = await tool_node(_state(_ai_message(
            _tool_call("create_network", {"name": "Existing"}, "t1"),
            _tool_call("add_place", {"name": "Orphan"}, "t2"),
        )))
        result = await tool_node(_state(
            _ai_message(_tool_call("import_pnml", {"xml": SAMPLE_PNML}, "t3")),
            net_data=built["net_data"],
        ))

        msg = result["messages"][0]
        assert getattr(msg, "status", "success") == "success"
        assert result["net_data"]["name"] == "Test Net"
        assert len(result["net_data"]["places"]) == 2

    @pytest.mark.asyncio
    async def test_import_reports_every_warning(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Bad ids</text></name>
    <place id="my place"><name><text>My Place</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="my place" target="t1"><inscription><text>1</text></inscription></arc>
  </net>
</pnml>"""
        state = _state(_ai_message(_tool_call("import_pnml", {"xml": xml}, "t1")))
        result = await tool_node(state)

        msg = result["messages"][0]
        assert getattr(msg, "status", "success") == "success"
        assert "Warnings" in msg.content
        assert "invalid-id" in msg.content

    @pytest.mark.asyncio
    async def test_import_malformed_xml_is_a_tool_error(self):
        state = _state(_ai_message(_tool_call("import_pnml", {"xml": "<not-pnml/>"}, "t1")))
        result = await tool_node(state)

        msg = result["messages"][0]
        assert msg.status == "error"
        assert "pnml" in msg.content.lower()


class TestNoToolCalls:
    @pytest.mark.asyncio
    async def test_ai_message_without_tool_calls_routes_to_respond(self):
        state = _state(AIMessage(content="hello"))
        result = await tool_node(state)
        assert result == {"next_action": "respond"}

    @pytest.mark.asyncio
    async def test_empty_messages_reports_error(self):
        result = await tool_node({"messages": [], "net_data": {}, "conversation_id": "c1"})
        assert result["error"] == "No messages to process"
        assert result["next_action"] == "end"
