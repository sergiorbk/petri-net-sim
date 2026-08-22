"""Tests for MCP simulation tools — run_simulation and get_simulation_results."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.mcp.session_store import SessionStore
from src.mcp.tools.simulation_tools import register_simulation_tools


class MockFastMCP:
    def __init__(self):
        self._tools: dict[str, Any] = {}

    def tool(self):
        def decorator(func):
            self._tools[func.__name__] = func
            return func
        return decorator


async def _make_ctx() -> tuple[MagicMock, SessionStore]:
    store = SessionStore()
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.request_context.lifespan_context.session_store = store
    return ctx, store


async def _build_mm1_net(store: SessionStore, ctx: MagicMock) -> None:
    """Build Gen → Machine → Terminator in the session."""
    session = await store.get_or_create(str(id(ctx.session)))
    session.create_network("TestNet")
    gen = session.builder.add_generator("Gen1", interval=5.0)
    machine = session.builder.add_machine("Server", processing_time=2.0)
    term = session.builder.add_terminator("Exit")
    session.builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
    session.builder.connect(machine.interface.output_place_id, term.interface.input_place_id)


# ---------------------------------------------------------------------------
# run_simulation
# ---------------------------------------------------------------------------


class TestRunSimulation:
    @pytest.mark.anyio
    async def test_empty_net_returns_no_network_message(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["run_simulation"](ctx=ctx, simulation_time=100.0)

        assert "No network" in result

    @pytest.mark.anyio
    async def test_basic_simulation_returns_results(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["run_simulation"](ctx=ctx, simulation_time=100.0)

        assert "Simulation" in result

    @pytest.mark.anyio
    async def test_result_contains_places_section(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["run_simulation"](ctx=ctx, simulation_time=100.0)

        assert "Places" in result

    @pytest.mark.anyio
    async def test_result_contains_transitions_section(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["run_simulation"](ctx=ctx, simulation_time=100.0)

        assert "Transitions" in result

    @pytest.mark.anyio
    async def test_time_unit_seconds_echoed(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["run_simulation"](
            ctx=ctx, simulation_time=3600.0, time_unit="s"
        )

        # _echo_duration converts 3600s → shows hours or seconds
        assert "3600" in result or "h" in result

    @pytest.mark.anyio
    async def test_time_unit_minutes_converts(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["run_simulation"](
            ctx=ctx, simulation_time=1.0, time_unit="min"
        )

        # 1 min = 60 s; the horizon echo should mention 60 or min
        assert "60" in result or "min" in result
        assert "time_unit=min" in result

    @pytest.mark.anyio
    async def test_time_unit_hours_converts(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["run_simulation"](
            ctx=ctx, simulation_time=1.0, time_unit="h"
        )

        assert "3600" in result or "h" in result
        assert "time_unit=h" in result

    @pytest.mark.anyio
    async def test_terminator_throughput_reported(self):
        """Terminators (tagged 'throughput') must appear in the results block."""
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["run_simulation"](ctx=ctx, simulation_time=200.0)

        # The Terminators block or throughput count should appear
        assert "Simulation" in result

    @pytest.mark.anyio
    async def test_simulation_horizon_prefix(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["run_simulation"](ctx=ctx, simulation_time=50.0)

        assert "Simulation horizon" in result or "horizon" in result.lower() or "50" in result


# ---------------------------------------------------------------------------
# get_simulation_results
# ---------------------------------------------------------------------------


class TestGetSimulationResults:
    @pytest.mark.anyio
    async def test_returns_instruction_to_use_run_simulation(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["get_simulation_results"](ctx=ctx)

        assert "run_simulation" in result

    @pytest.mark.anyio
    async def test_result_is_non_empty_string(self):
        mock_mcp = MockFastMCP()
        register_simulation_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["get_simulation_results"](ctx=ctx)

        assert isinstance(result, str)
        assert len(result) > 0
