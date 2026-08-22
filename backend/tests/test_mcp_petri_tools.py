"""Tests for MCP petri_tools -- tool registration and tool functions via mock context.

The time-unit conversion, annotation-mapping, and doc-merge helpers this
module used to hand-roll now live in the shared agent_toolkit package and
are covered there: see test_agent_toolkit_time_units.py and
test_agent_toolkit_catalog.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.mcp.session_store import SessionStore
from src.mcp.tools.petri_tools import register_petri_tools
from src.services.petri.agent_toolkit.catalog import EXPLICIT_PATTERN_NAMES


# ---------------------------------------------------------------------------
# Helper: minimal FastMCP mock that captures @mcp.tool() registrations
# ---------------------------------------------------------------------------

class MockFastMCP:
    def __init__(self):
        self._tools: dict[str, Any] = {}

    def tool(self):
        def decorator(func):
            self._tools[func.__name__] = func
            return func
        return decorator


async def _make_ctx(session_id: str = "test") -> tuple[MagicMock, SessionStore]:
    store = SessionStore()
    await store.get_or_create(session_id)
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.request_context.lifespan_context.session_store = store
    return ctx, store


# ---------------------------------------------------------------------------
# register_petri_tools registration smoke test
# ---------------------------------------------------------------------------

class TestRegisterPetriTools:
    def test_registers_expected_tools(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        assert "create_network" in mock_mcp._tools
        assert "add_generator" in mock_mcp._tools
        assert "add_machine" in mock_mcp._tools
        assert "connect_patterns" in mock_mcp._tools
        assert "get_network_status" in mock_mcp._tools
        assert "add_place" in mock_mcp._tools
        assert "add_transition" in mock_mcp._tools
        assert "add_arc" in mock_mcp._tools

    def test_auto_generated_tools_registered(self):
        from src.domain.patterns.registry import get_registry
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        registry = get_registry()
        for name in registry:
            if name not in EXPLICIT_PATTERN_NAMES:
                assert f"add_{name}" in mock_mcp._tools, f"Missing auto-generated tool: add_{name}"


# ---------------------------------------------------------------------------
# Explicit tool invocation via mock ctx
# ---------------------------------------------------------------------------

class TestCreateNetwork:
    @pytest.mark.anyio
    async def test_create_network(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["create_network"](ctx=ctx, name="TestNet")
        assert "TestNet" in result

    @pytest.mark.anyio
    async def test_create_network_default_name(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["create_network"](ctx=ctx)
        assert "PetriNet" in result


class TestAddGenerator:
    @pytest.mark.anyio
    async def test_add_generator_with_interval(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_generator"](
            ctx=ctx, name="Gen1", interval=5.0, time_unit="s"
        )
        assert "Gen1" in result
        assert "Output" in result

    @pytest.mark.anyio
    async def test_add_generator_with_rate(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_generator"](
            ctx=ctx, name="Gen2", rate=4.0, time_unit="min"
        )
        assert "Gen2" in result
        # rate=4/min → interval = 60/4 = 15s; verify conversion was applied
        assert "15" in result, f"Expected 15s interval in response, got: {result}"
        assert "time_unit=min" in result

    @pytest.mark.anyio
    async def test_add_generator_rate_one_per_minute(self):
        """rate=1/min must produce interval=60s, not 1s (regression guard)."""
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_generator"](
            ctx=ctx, name="GenReg", rate=1.0, time_unit="min"
        )
        assert "60" in result, f"Expected 60s interval in response, got: {result}"
        assert "time_unit=min" in result

    @pytest.mark.anyio
    async def test_add_generator_with_batch(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_generator"](
            ctx=ctx, name="Gen3", interval=1.0, batch_size=5
        )
        assert "batch_size=5" in result

    @pytest.mark.anyio
    async def test_add_generator_defaults_to_interval_1(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_generator"](ctx=ctx, name="Gen4")
        assert "Gen4" in result


class TestAddMachine:
    @pytest.mark.anyio
    async def test_add_machine_basic(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_machine"](
            ctx=ctx, name="M1", processing_time=10.0
        )
        assert "M1" in result
        assert "Input" in result
        assert "Output" in result

    @pytest.mark.anyio
    async def test_add_machine_with_time_unit(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_machine"](
            ctx=ctx, name="M2", processing_time=2.0, time_unit="min"
        )
        assert "120" in result  # 2 min = 120s
        assert "time_unit=min" in result

    @pytest.mark.anyio
    async def test_add_machine_no_auto_connect(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_machine"](
            ctx=ctx, name="M3", processing_time=5.0, auto_connect=False
        )
        assert "M3" in result


class TestAddController:
    @pytest.mark.anyio
    async def test_add_controller_disabled(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_controller"](ctx=ctx, name="Gate1")
        assert "disabled" in result

    @pytest.mark.anyio
    async def test_add_controller_enabled(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_controller"](
            ctx=ctx, name="Gate2", initial_signal=True
        )
        assert "enabled" in result


class TestAddAssembly:
    @pytest.mark.anyio
    async def test_add_assembly_simple_inputs(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_assembly"](
            ctx=ctx, name="Asm1", inputs=["PartA", "PartB"]
        )
        assert "Asm1" in result
        assert "PartA" in result


class TestAddRouter:
    @pytest.mark.anyio
    async def test_add_router_probability(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_router"](
            ctx=ctx,
            name="Router1",
            routes=[{"name": "Accept", "prob": 0.9}, {"name": "Reject", "prob": 0.1}],
            strategy="probability",
        )
        assert "Router1" in result
        assert "probability" in result


class TestAddConveyor:
    @pytest.mark.anyio
    async def test_add_conveyor(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_conveyor"](
            ctx=ctx,
            name="Conv1",
            stations=[{"name": "S1", "time": 10.0, "distribution": "exp"}],
        )
        assert "Conv1" in result
        assert "Entry" in result


class TestAddConveyorWorkstation:
    @pytest.mark.anyio
    async def test_add_conveyor_workstation(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_conveyor_workstation"](
            ctx=ctx, name="WS1", processing_time=10.0
        )
        assert "WS1" in result
        assert "Input" in result


class TestAddTransportAgent:
    @pytest.mark.anyio
    async def test_add_transport_agent_defaults(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_transport_agent"](ctx=ctx, name="Robot1")
        assert "Robot1" in result
        assert "Queue" in result

    @pytest.mark.anyio
    async def test_add_transport_agent_with_return_time(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_transport_agent"](
            ctx=ctx, name="Robot2", return_time=12.0
        )
        assert "Robot2" in result


class TestAddPriorityChoice:
    @pytest.mark.anyio
    async def test_add_priority_choice(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_priority_choice"](ctx=ctx, name="PC1")
        assert "PC1" in result
        assert "Input" in result


class TestAddMerge:
    @pytest.mark.anyio
    async def test_add_merge(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_merge"](
            ctx=ctx, name="Merge1", inputs=["A", "B"]
        )
        assert "Merge1" in result
        assert "A" in result


class TestAddDuplicate:
    @pytest.mark.anyio
    async def test_add_duplicate(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_duplicate"](
            ctx=ctx, name="Dup1", outputs=["X", "Y"]
        )
        assert "Dup1" in result


class TestAddMultiResource:
    @pytest.mark.anyio
    async def test_add_multi_resource(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_multi_resource"](
            ctx=ctx,
            name="MR1",
            resources=[{"name": "Worker", "pool_size": 2}, {"name": "Machine", "pool_size": 1}],
            processing_time=15.0,
        )
        assert "MR1" in result
        assert "Worker" in result


class TestAddNonstationaryGenerator:
    @pytest.mark.anyio
    async def test_add_nonstationary_generator(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        schedule = [
            {"duration": 7200.0, "rate": 0.1},
            {"duration": 14400.0, "rate": 0.05},
        ]
        result = await mock_mcp._tools["add_nonstationary_generator"](
            ctx=ctx, name="NGGen1", schedule=schedule
        )
        assert "NGGen1" in result
        assert "2 windows" in result


class TestAddForkJoin:
    @pytest.mark.anyio
    async def test_add_fork_join_defaults(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_fork_join"](ctx=ctx, name="FJ1")
        assert "FJ1" in result
        assert "2 branches" in result

    @pytest.mark.anyio
    async def test_add_fork_join_custom_times(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_fork_join"](
            ctx=ctx, name="FJ2", n_branches=3, branch_times=[10.0, 20.0, 30.0]
        )
        assert "3 branches" in result


class TestAddResourceSet:
    @pytest.mark.anyio
    async def test_add_resource_set(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_resource_set"](
            ctx=ctx,
            name="RS1",
            resources=[
                {"name": "Fast", "service_time": 30.0},
                {"name": "Slow", "service_time": 90.0},
            ],
        )
        assert "RS1" in result
        assert "Fast" in result


class TestAddConveyorLine:
    @pytest.mark.anyio
    async def test_add_conveyor_line(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_conveyor_line"](
            ctx=ctx, station_count=2, processing_time=10.0
        )
        assert "2 stations" in result


class TestConnectPatterns:
    @pytest.mark.anyio
    async def test_connect_patterns(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()

        # Build a net with two patterns to get real IDs
        session = await store.get_or_create(str(id(ctx.session)))
        session.create_network("Test")
        gen = session.builder.add_generator("Gen1", interval=5.0)
        machine = session.builder.add_machine("M1", processing_time=10.0)

        result = await mock_mcp._tools["connect_patterns"](
            ctx=ctx,
            source_output_id=gen.interface.output_place_id,
            target_input_id=machine.interface.input_place_id,
        )
        assert "->" in result


class TestGetNetworkStatus:
    @pytest.mark.anyio
    async def test_status_empty_network(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["get_network_status"](ctx=ctx)
        assert "No network" in result

    @pytest.mark.anyio
    async def test_status_with_network(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await store.get_or_create(str(id(ctx.session)))
        session.builder.add_generator("Gen1", interval=5.0)

        result = await mock_mcp._tools["get_network_status"](ctx=ctx)
        assert "Gen1" in result or "Network" in result


class TestLowLevelTools:
    @pytest.mark.anyio
    async def test_add_place(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_place"](ctx=ctx, name="MyPlace", tokens=3)
        assert "MyPlace" in result
        assert "3" in result

    @pytest.mark.anyio
    async def test_add_transition_immediate(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_transition"](ctx=ctx, name="Fire")
        assert "Fire" in result
        assert "immediate" in result

    @pytest.mark.anyio
    async def test_add_transition_timed(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_transition"](
            ctx=ctx, name="Process", distribution="exp", mean_delay=5.0
        )
        assert "Process" in result
        assert "exp" in result

    @pytest.mark.anyio
    async def test_add_arc(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await store.get_or_create(str(id(ctx.session)))
        pid = session.builder.add_raw_place("P1")
        tid = session.builder.add_raw_transition("T1", mean_delay=5.0)

        result = await mock_mcp._tools["add_arc"](
            ctx=ctx, source_id=pid, target_id=tid
        )
        assert "arc" in result.lower() or pid in result


class TestConnectBoundedConsumer:
    @pytest.mark.anyio
    async def test_error_when_queue_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["connect_bounded_consumer"](
            ctx=ctx, queue_name="NonExistent", consumer_name="M1"
        )
        assert "Error" in result

    @pytest.mark.anyio
    async def test_error_when_consumer_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await store.get_or_create(str(id(ctx.session)))
        session.builder.add_bounded_queue("BQ1", capacity=5)

        result = await mock_mcp._tools["connect_bounded_consumer"](
            ctx=ctx, queue_name="BQ1", consumer_name="NonExistentMachine"
        )
        assert "Error" in result

    @pytest.mark.anyio
    async def test_success_wires_capacity(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await store.get_or_create(str(id(ctx.session)))
        bq = session.builder.add_bounded_queue("BQ1", capacity=5)
        m = session.builder.add_machine("M1", processing_time=5.0)
        session.builder.connect(bq.interface.output_place_id, m.interface.input_place_id)

        result = await mock_mcp._tools["connect_bounded_consumer"](
            ctx=ctx, queue_name="BQ1", consumer_name="M1"
        )
        assert "recycling" in result or "Wired" in result


class TestConnectBlockingConsumer:
    @pytest.mark.anyio
    async def test_error_when_blocking_machine_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["connect_blocking_consumer"](
            ctx=ctx, blocking_machine_name="NonExistent", downstream_name="M1"
        )
        assert "Error" in result


class TestConnectWorkstationBypass:
    @pytest.mark.anyio
    async def test_error_source_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["connect_workstation_bypass"](
            ctx=ctx, source_workstation_name="WS_NoExist", target_workstation_name="WS2"
        )
        assert "Error" in result

    @pytest.mark.anyio
    async def test_error_target_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await store.get_or_create(str(id(ctx.session)))
        session.builder.add_conveyor_workstation("WS1", processing_time=10.0)

        result = await mock_mcp._tools["connect_workstation_bypass"](
            ctx=ctx, source_workstation_name="WS1", target_workstation_name="WS_NoExist"
        )
        assert "Error" in result


class TestConnectReturnLoop:
    @pytest.mark.anyio
    async def test_error_last_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["connect_return_loop"](
            ctx=ctx, last_workstation_name="NoExist", first_workstation_name="WS1"
        )
        assert "Error" in result

    @pytest.mark.anyio
    async def test_error_first_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await store.get_or_create(str(id(ctx.session)))
        session.builder.add_conveyor_workstation("WS1", processing_time=10.0)

        result = await mock_mcp._tools["connect_return_loop"](
            ctx=ctx, last_workstation_name="WS1", first_workstation_name="NoExist"
        )
        assert "Error" in result

    @pytest.mark.anyio
    async def test_success_with_two_workstations(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await store.get_or_create(str(id(ctx.session)))
        session.builder.add_conveyor_workstation("WS1", processing_time=10.0)
        session.builder.add_conveyor_workstation("WS2", processing_time=10.0)

        result = await mock_mcp._tools["connect_return_loop"](
            ctx=ctx, last_workstation_name="WS2", first_workstation_name="WS1"
        )
        assert "WS2" in result
        assert "WS1" in result


class TestConnectWipReturn:
    @pytest.mark.anyio
    async def test_error_wip_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["connect_wip_return"](
            ctx=ctx, wip_controller_name="NoWip", exit_place_id="p1"
        )
        assert "Error" in result


class TestConnectScheduleGate:
    @pytest.mark.anyio
    async def test_error_schedule_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["connect_schedule_gate"](
            ctx=ctx, schedule_name="NoSched", machine_name="M1"
        )
        assert "Error" in result

    @pytest.mark.anyio
    async def test_error_machine_not_found(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await store.get_or_create(str(id(ctx.session)))
        session.builder.add_scheduled_availability("Shift1")

        result = await mock_mcp._tools["connect_schedule_gate"](
            ctx=ctx, schedule_name="Shift1", machine_name="NoMachine"
        )
        assert "Error" in result


class TestAutoGeneratedTools:
    @pytest.mark.anyio
    async def test_auto_generated_buffer(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_buffer"](ctx=ctx, name="Buf1")
        assert "Buf1" in result

    @pytest.mark.anyio
    async def test_auto_generated_terminator(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_terminator"](ctx=ctx, name="Exit1")
        assert "Exit1" in result

    @pytest.mark.anyio
    async def test_auto_generated_quality_check(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_quality_check"](ctx=ctx, name="QC1")
        assert "QC1" in result

    @pytest.mark.anyio
    async def test_auto_generated_feedback_loop(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_feedback_loop"](ctx=ctx, name="FB1")
        assert "FB1" in result

    @pytest.mark.anyio
    async def test_auto_generated_breakdown(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_breakdown"](ctx=ctx, name="BD1")
        assert "BD1" in result

    @pytest.mark.anyio
    async def test_auto_generated_bounded_queue(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_bounded_queue"](ctx=ctx, name="BQ1")
        assert "BQ1" in result

    @pytest.mark.anyio
    async def test_auto_generated_batch(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_batch"](ctx=ctx, name="Batch1")
        assert "Batch1" in result

    @pytest.mark.anyio
    async def test_auto_generated_unbatch(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_unbatch"](ctx=ctx, name="Unbatch1")
        assert "Unbatch1" in result

    @pytest.mark.anyio
    async def test_auto_generated_timed_batch(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_timed_batch"](ctx=ctx, name="TB1")
        assert "TB1" in result

    @pytest.mark.anyio
    async def test_auto_generated_reneging_queue(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_reneging_queue"](ctx=ctx, name="RQ1")
        assert "RQ1" in result

    @pytest.mark.anyio
    async def test_auto_generated_balking_queue(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_balking_queue"](ctx=ctx, name="BalkQ1")
        assert "BalkQ1" in result

    @pytest.mark.anyio
    async def test_auto_generated_server_vacation(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_server_vacation"](ctx=ctx, name="SV1")
        assert "SV1" in result

    @pytest.mark.anyio
    async def test_auto_generated_preemptive_machine(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_preemptive_machine"](ctx=ctx, name="PM1")
        assert "PM1" in result

    @pytest.mark.anyio
    async def test_auto_generated_setup_machine(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_setup_machine"](ctx=ctx, name="SM1")
        assert "SM1" in result

    @pytest.mark.anyio
    async def test_auto_generated_scheduled_availability(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_scheduled_availability"](ctx=ctx, name="Sched1")
        assert "Sched1" in result

    @pytest.mark.anyio
    async def test_auto_generated_threshold_activation(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_threshold_activation"](ctx=ctx, name="TA1")
        assert "TA1" in result

    @pytest.mark.anyio
    async def test_auto_generated_retrial_queue(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_retrial_queue"](ctx=ctx, name="RetQ1")
        assert "RetQ1" in result

    @pytest.mark.anyio
    async def test_auto_generated_finite_population_queue(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_finite_population_queue"](ctx=ctx, name="FPQ1")
        assert "FPQ1" in result

    @pytest.mark.anyio
    async def test_auto_generated_wip_controller(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_wip_controller"](ctx=ctx, name="WIP1")
        assert "WIP1" in result

    @pytest.mark.anyio
    async def test_auto_generated_blocking_machine(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()
        result = await mock_mcp._tools["add_blocking_machine"](ctx=ctx, name="BLM1")
        assert "BLM1" in result

    @pytest.mark.anyio
    async def test_auto_connect_in_auto_generated_tool(self):
        """Auto-connect fires when two patterns added sequentially."""
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        # Add generator first (sets last output)
        await mock_mcp._tools["add_generator"](ctx=ctx, name="Gen1", interval=5.0)
        # Buffer should auto-connect from generator output
        result = await mock_mcp._tools["add_buffer"](ctx=ctx, name="Buf1")
        assert "Auto-connected" in result or "Input" in result

    @pytest.mark.anyio
    async def test_time_unit_conversion_in_auto_generated(self):
        """Auto-generated tools convert time_unit properly."""
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()

        await mock_mcp._tools["add_breakdown"](
            ctx=ctx, name="BD1", mean_time_between_failures=2.0, time_unit="min"
        )
        session = await store.get_or_create(str(id(ctx.session)))
        # Find the MTBF transition and check it uses 120s
        mtbf_trans = next(
            (t for t in session.net.transitions if "BD1" in t.name and "Fail" in t.name),
            None,
        )
        if mtbf_trans is not None:
            assert mtbf_trans.mean_delay == pytest.approx(120.0)


class TestAutoOptimizeEnabled:
    """C1: the MCP session store constructs PetriNetSession() with the
    session-level auto_optimize switch at its default (True), so connecting
    two patterns still eagerly fuses the Transfer transition, unchanged
    from before the switch existed. See TestAutoOptimizeDisabled in
    test_agent_tool_node.py for the chat surface's opposite behavior.
    """

    @pytest.mark.anyio
    async def test_transfer_transition_gets_fused_without_explicit_optimize(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()

        await mock_mcp._tools["add_generator"](ctx=ctx, name="Gen1", interval=1.0)
        await mock_mcp._tools["add_machine"](ctx=ctx, name="M1", processing_time=1.0)

        session = await store.get_or_create(str(id(ctx.session)))
        assert not any(t.name.startswith("Transfer_") for t in session.net.transitions)
        assert session._is_optimized is True


class TestUnknownKwargFiltering:
    """C5: a hallucinated parameter name is dropped before it ever reaches
    spec.operation(session, **kwargs), instead of surfacing a raw TypeError
    naming the internal op_* function. MockFastMCP calls _impl directly
    (bypassing FastMCP's own arg-validation model), so this exercises the
    same defense-in-depth filter as a real client that got past validation.
    """

    @pytest.mark.anyio
    async def test_stray_kwarg_on_add_machine_is_ignored(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["add_machine"](
            ctx=ctx, name="M1", processing_time=5.0, bogus_param=1,
        )
        assert "M1" in result
        assert "Ignored unknown parameter(s): bogus_param" in result


class TestImportPnml:
    """Part B: import_pnml on the MCP surface. import_pnml falls through
    to register_petri_tools (it is neither an export/optimize name nor a
    simulation name -- see petri_tools.py's EXPORT_TOOL_NAMES/
    SIMULATION_TOOL_NAMES), so it is exercised through the same
    MockFastMCP/register_petri_tools harness as every other tool in this
    file, unlike export_pnml which lives in test_mcp_export_tools.py.
    """

    @pytest.mark.anyio
    async def test_import_replaces_an_empty_session(self):
        from tests.test_pnml_importer import SAMPLE_PNML

        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()

        result = await mock_mcp._tools["import_pnml"](ctx=ctx, xml=SAMPLE_PNML)

        assert "2 place(s)" in result
        assert "1 transition(s)" in result
        assert "2 arc(s)" in result
        session = await store.get_or_create(str(id(ctx.session)))
        assert session.net.name == "Test Net"
        assert len(session.net.places) == 2

    @pytest.mark.anyio
    async def test_import_refuses_when_replace_false_and_session_non_empty(self):
        from tests.test_pnml_importer import SAMPLE_PNML

        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()

        await mock_mcp._tools["add_place"](ctx=ctx, name="Existing")
        result = await mock_mcp._tools["import_pnml"](
            ctx=ctx, xml=SAMPLE_PNML, replace=False,
        )

        assert result.startswith("Error:")
        assert "replace" in result.lower()
        # Untouched: the session's own place from before the import survives.
        session = await store.get_or_create(str(id(ctx.session)))
        assert len(session.net.places) == 1
        assert session.net.places[0].name == "Existing"

    @pytest.mark.anyio
    async def test_import_with_replace_true_overwrites_non_empty_session(self):
        from tests.test_pnml_importer import SAMPLE_PNML

        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()

        await mock_mcp._tools["add_place"](ctx=ctx, name="Existing")
        result = await mock_mcp._tools["import_pnml"](ctx=ctx, xml=SAMPLE_PNML)

        assert "Imported 'Test Net'" in result
        session = await store.get_or_create(str(id(ctx.session)))
        assert session.net.name == "Test Net"
        assert [p.name for p in session.net.places] == ["Input", "Output"]

    @pytest.mark.anyio
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
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["import_pnml"](ctx=ctx, xml=xml)

        assert "Warnings" in result
        assert "invalid-id" in result
        assert "my-place" in result

    @pytest.mark.anyio
    async def test_import_malformed_xml_is_a_tool_error(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["import_pnml"](ctx=ctx, xml="<not-pnml/>")

        assert result.startswith("Error:")
        assert "pnml" in result.lower()

    @pytest.mark.anyio
    async def test_import_composed_document_produces_objects_and_links(self):
        """A composed (multi-page, Petri-object) PNML document round-trips
        through export_pnml -> import_pnml and lands back as a composed
        session (named objects, a cross-object link), not a flat one."""
        from src.domain.composed import LinkType
        from src.services.petri.session import PetriNetSession

        source = PetriNetSession()
        source.create_object("Loader")
        p1 = source.builder.add_raw_place("P1")
        source.create_object("Sink")
        p2 = source.builder.add_raw_place("P2")
        source.set_active_object(0)
        t1 = source.builder.add_raw_transition("T1", mean_delay=1.0)
        source.net.add_arc(source_id=p1, target_id=t1)
        source.add_link(
            LinkType.TRANSITION_TO_PLACE,
            source.objects[0].frame_id, t1,
            source.objects[1].frame_id, p2,
        )
        xml = source.export_pnml()

        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()

        result = await mock_mcp._tools["import_pnml"](ctx=ctx, xml=xml)

        assert "object(s)" in result
        assert "link(s)" in result
        session = await store.get_or_create(str(id(ctx.session)))
        assert session.is_composed
        assert {o.name for o in session.objects} == {"Loader", "Sink"}
        assert len(session.links) == 1
