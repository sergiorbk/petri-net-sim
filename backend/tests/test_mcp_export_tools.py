"""Tests for MCP export tools — optimize_network and export_pnml."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.mcp.session_store import SessionStore
from src.mcp.tools.export_tools import register_export_tools


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
    """Build a simple M/M/1 queue (Gen → Machine → Terminator) in the session."""
    session = await store.get_or_create(str(id(ctx.session)))
    session.create_network("TestNet")
    gen = session.builder.add_generator("Gen1", interval=10.0)
    machine = session.builder.add_machine("Server", processing_time=5.0)
    term = session.builder.add_terminator("Exit")
    session.builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
    session.builder.connect(machine.interface.output_place_id, term.interface.input_place_id)


# ---------------------------------------------------------------------------
# optimize_network
# ---------------------------------------------------------------------------


class TestOptimizeNetwork:
    @pytest.mark.anyio
    async def test_empty_net_returns_no_network_message(self):
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["optimize_network"](ctx=ctx)

        assert "No network" in result

    @pytest.mark.anyio
    async def test_optimize_reports_before_and_after(self):
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["optimize_network"](ctx=ctx)

        assert "Before" in result
        assert "After" in result

    @pytest.mark.anyio
    async def test_optimize_reports_fusions(self):
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["optimize_network"](ctx=ctx)

        assert "Fusions" in result or "fusions" in result

    @pytest.mark.anyio
    async def test_optimize_does_not_increase_element_count(self):
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)
        session = await store.get_or_create(str(id(ctx.session)))
        places_before = len(session.net.places)
        transitions_before = len(session.net.transitions)

        await mock_mcp._tools["optimize_network"](ctx=ctx)

        assert len(session.net.places) <= places_before
        assert len(session.net.transitions) <= transitions_before

    @pytest.mark.anyio
    async def test_optimize_preserves_semantic_places(self):
        """Tagged 'throughput' places must survive optimization."""
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)
        session = await store.get_or_create(str(id(ctx.session)))

        await mock_mcp._tools["optimize_network"](ctx=ctx)

        throughput_places = [p for p in session.net.places if p.tag == "throughput"]
        assert len(throughput_places) >= 1

    @pytest.mark.anyio
    async def test_optimize_idempotent(self):
        """Running optimize twice should not error and the second pass removes nothing extra."""
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        await mock_mcp._tools["optimize_network"](ctx=ctx)
        session = await store.get_or_create(str(id(ctx.session)))
        places_after_first = len(session.net.places)

        result2 = await mock_mcp._tools["optimize_network"](ctx=ctx)

        assert len(session.net.places) == places_after_first
        assert "Before" in result2  # still reports stats


# ---------------------------------------------------------------------------
# export_pnml
# ---------------------------------------------------------------------------


class TestExportPNML:
    @pytest.mark.anyio
    async def test_empty_net_returns_no_network_message(self):
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["export_pnml"](ctx=ctx)

        assert "No network" in result

    @pytest.mark.anyio
    async def test_export_returns_valid_xml(self):
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["export_pnml"](ctx=ctx)

        assert "<?xml" in result
        assert "<pnml" in result
        assert "</pnml>" in result

    @pytest.mark.anyio
    async def test_export_contains_net_name(self):
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["export_pnml"](ctx=ctx)

        assert "TestNet" in result

    @pytest.mark.anyio
    async def test_export_contains_pattern_names(self):
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        result = await mock_mcp._tools["export_pnml"](ctx=ctx)

        assert "Gen1" in result
        assert "Server" in result

    @pytest.mark.anyio
    async def test_export_after_optimize_still_valid(self):
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        await _build_mm1_net(store, ctx)

        await mock_mcp._tools["optimize_network"](ctx=ctx)
        result = await mock_mcp._tools["export_pnml"](ctx=ctx)

        assert "<pnml" in result
        assert "TestNet" in result

    @pytest.mark.anyio
    async def test_export_raw_net(self):
        """Low-level (raw) nets are also exportable."""
        mock_mcp = MockFastMCP()
        register_export_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await store.get_or_create(str(id(ctx.session)))
        session.create_network("RawNet")
        p1 = session.builder.add_raw_place("Input", tokens=3)
        t1 = session.builder.add_raw_transition("Process", mean_delay=5.0)
        p2 = session.builder.add_raw_place("Output")
        session.builder.add_raw_arc(p1, t1)
        session.builder.add_raw_arc(t1, p2)

        result = await mock_mcp._tools["export_pnml"](ctx=ctx)

        assert "<pnml" in result
        assert "Input" in result
        assert "Process" in result
        assert "Output" in result
