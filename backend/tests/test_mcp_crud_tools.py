"""Tests for MCP CRUD tools — modify_*, remove_*, validate_net, list_elements."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.mcp.session_store import SessionStore
from src.mcp.tools.petri_tools import register_petri_tools


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


async def _get_session(store: SessionStore, ctx: MagicMock):
    return await store.get_or_create(str(id(ctx.session)))


# ---------------------------------------------------------------------------
# modify_place
# ---------------------------------------------------------------------------


class TestModifyPlaceTool:
    @pytest.mark.anyio
    async def test_modify_tokens(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1", tokens=0)

        result = await mock_mcp._tools["modify_place"](ctx=ctx, place_id=pid, tokens=5)

        assert session.net.get_place(pid).tokens == 5
        assert "P1" in result or "5" in result

    @pytest.mark.anyio
    async def test_modify_name(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("OldName")

        result = await mock_mcp._tools["modify_place"](ctx=ctx, place_id=pid, name="NewName")

        assert session.net.get_place(pid).name == "NewName"
        assert "NewName" in result

    @pytest.mark.anyio
    async def test_modify_tag(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")

        await mock_mcp._tools["modify_place"](ctx=ctx, place_id=pid, tag="throughput")

        assert session.net.get_place(pid).tag == "throughput"

    @pytest.mark.anyio
    async def test_unchanged_fields_preserved(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1", tokens=7, tag="counter")

        await mock_mcp._tools["modify_place"](ctx=ctx, place_id=pid, name="P1_renamed")

        place = session.net.get_place(pid)
        assert place.tokens == 7
        assert place.tag == "counter"
        assert place.name == "P1_renamed"

    @pytest.mark.anyio
    async def test_nonexistent_place_returns_error(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["modify_place"](ctx=ctx, place_id="nonexistent", tokens=1)

        assert "Error" in result or "not found" in result.lower()

    @pytest.mark.anyio
    async def test_negative_tokens_returns_error(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")

        result = await mock_mcp._tools["modify_place"](ctx=ctx, place_id=pid, tokens=-3)

        assert "Error" in result


# ---------------------------------------------------------------------------
# modify_transition
# ---------------------------------------------------------------------------


class TestModifyTransitionTool:
    @pytest.mark.anyio
    async def test_modify_mean_delay(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        tid = session.builder.add_raw_transition("T1", mean_delay=5.0)

        result = await mock_mcp._tools["modify_transition"](ctx=ctx, transition_id=tid, mean_delay=20.0)

        assert session.net.get_transition(tid).mean_delay == 20.0
        assert "T1" in result or "20" in result

    @pytest.mark.anyio
    async def test_modify_name(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        tid = session.builder.add_raw_transition("OldTrans")

        result = await mock_mcp._tools["modify_transition"](ctx=ctx, transition_id=tid, name="NewTrans")

        assert session.net.get_transition(tid).name == "NewTrans"
        assert "NewTrans" in result

    @pytest.mark.anyio
    async def test_modify_priority(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        tid = session.builder.add_raw_transition("T1")

        await mock_mcp._tools["modify_transition"](ctx=ctx, transition_id=tid, priority=5)

        assert session.net.get_transition(tid).priority == 5

    @pytest.mark.anyio
    async def test_unchanged_fields_preserved(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        tid = session.builder.add_raw_transition("T1", mean_delay=10.0, priority=3)

        await mock_mcp._tools["modify_transition"](ctx=ctx, transition_id=tid, name="T1_renamed")

        trans = session.net.get_transition(tid)
        assert trans.mean_delay == 10.0
        assert trans.priority == 3
        assert trans.name == "T1_renamed"

    @pytest.mark.anyio
    async def test_nonexistent_transition_returns_error(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["modify_transition"](
            ctx=ctx, transition_id="nonexistent", mean_delay=1.0
        )

        assert "Error" in result or "not found" in result.lower()


# ---------------------------------------------------------------------------
# modify_arc
# ---------------------------------------------------------------------------


class TestModifyArcTool:
    @pytest.mark.anyio
    async def test_modify_weight(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")
        tid = session.builder.add_raw_transition("T1")
        aid = session.builder.add_raw_arc(pid, tid, weight=1)

        result = await mock_mcp._tools["modify_arc"](ctx=ctx, arc_id=aid, weight=5)

        assert session.net.get_arc(aid).weight == 5
        assert "5" in result or "arc" in result.lower()

    @pytest.mark.anyio
    async def test_modify_arc_type_to_read(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")
        tid = session.builder.add_raw_transition("T1")
        aid = session.builder.add_raw_arc(pid, tid)

        await mock_mcp._tools["modify_arc"](ctx=ctx, arc_id=aid, arc_type="read")

        assert session.net.get_arc(aid).is_read_arc

    @pytest.mark.anyio
    async def test_modify_arc_type_to_inhibitor(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")
        tid = session.builder.add_raw_transition("T1")
        aid = session.builder.add_raw_arc(pid, tid)

        await mock_mcp._tools["modify_arc"](ctx=ctx, arc_id=aid, arc_type="inhibitor")

        assert session.net.get_arc(aid).is_inhibitor

    @pytest.mark.anyio
    async def test_nonexistent_arc_returns_error(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["modify_arc"](ctx=ctx, arc_id="nonexistent", weight=2)

        assert "Error" in result or "not found" in result.lower()


# ---------------------------------------------------------------------------
# remove_place
# ---------------------------------------------------------------------------


class TestRemovePlaceTool:
    @pytest.mark.anyio
    async def test_remove_place(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")

        result = await mock_mcp._tools["remove_place"](ctx=ctx, place_id=pid)

        assert session.net.get_place(pid) is None
        assert "P1" in result or "removed" in result.lower()

    @pytest.mark.anyio
    async def test_remove_place_cascades_arcs(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")
        tid = session.builder.add_raw_transition("T1")
        session.builder.add_raw_arc(pid, tid)
        assert len(session.net.arcs) == 1

        await mock_mcp._tools["remove_place"](ctx=ctx, place_id=pid)

        assert len(session.net.arcs) == 0

    @pytest.mark.anyio
    async def test_remove_place_nonexistent_returns_error(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["remove_place"](ctx=ctx, place_id="nonexistent")

        assert "Error" in result or "not found" in result.lower()


# ---------------------------------------------------------------------------
# remove_transition
# ---------------------------------------------------------------------------


class TestRemoveTransitionTool:
    @pytest.mark.anyio
    async def test_remove_transition(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        tid = session.builder.add_raw_transition("T1")

        result = await mock_mcp._tools["remove_transition"](ctx=ctx, transition_id=tid)

        assert session.net.get_transition(tid) is None
        assert "T1" in result or "removed" in result.lower()

    @pytest.mark.anyio
    async def test_remove_transition_cascades_arcs(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")
        tid = session.builder.add_raw_transition("T1")
        session.builder.add_raw_arc(pid, tid)
        assert len(session.net.arcs) == 1

        await mock_mcp._tools["remove_transition"](ctx=ctx, transition_id=tid)

        assert len(session.net.arcs) == 0

    @pytest.mark.anyio
    async def test_remove_transition_nonexistent_returns_error(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["remove_transition"](ctx=ctx, transition_id="nonexistent")

        assert "Error" in result or "not found" in result.lower()


# ---------------------------------------------------------------------------
# remove_arc
# ---------------------------------------------------------------------------


class TestRemoveArcTool:
    @pytest.mark.anyio
    async def test_remove_arc(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")
        tid = session.builder.add_raw_transition("T1")
        aid = session.builder.add_raw_arc(pid, tid)

        result = await mock_mcp._tools["remove_arc"](ctx=ctx, arc_id=aid)

        assert session.net.get_arc(aid) is None
        assert "arc" in result.lower() or "removed" in result.lower()

    @pytest.mark.anyio
    async def test_remove_arc_preserves_nodes(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")
        tid = session.builder.add_raw_transition("T1")
        aid = session.builder.add_raw_arc(pid, tid)

        await mock_mcp._tools["remove_arc"](ctx=ctx, arc_id=aid)

        assert session.net.get_place(pid) is not None
        assert session.net.get_transition(tid) is not None

    @pytest.mark.anyio
    async def test_remove_arc_nonexistent_returns_error(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["remove_arc"](ctx=ctx, arc_id="nonexistent")

        assert "Error" in result or "not found" in result.lower()


# ---------------------------------------------------------------------------
# validate_net
# ---------------------------------------------------------------------------


class TestValidateNetTool:
    @pytest.mark.anyio
    async def test_validate_empty_net(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["validate_net"](ctx=ctx)

        assert "No network" in result or "empty" in result.lower() or "valid" in result.lower()

    @pytest.mark.anyio
    async def test_validate_correct_net(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        p1 = session.builder.add_raw_place("P1", tokens=1)
        t1 = session.builder.add_raw_transition("T1", mean_delay=5.0)
        p2 = session.builder.add_raw_place("P2")
        session.builder.add_raw_arc(p1, t1)
        session.builder.add_raw_arc(t1, p2)

        result = await mock_mcp._tools["validate_net"](ctx=ctx)

        assert "valid" in result.lower() or "0 error" in result.lower() or "ok" in result.lower()

    @pytest.mark.anyio
    async def test_validate_dangling_transition_reports_errors(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        p1 = session.builder.add_raw_place("P1")
        t1 = session.builder.add_raw_transition("T1")
        session.builder.add_raw_arc(t1, p1)  # only output arc — no input

        result = await mock_mcp._tools["validate_net"](ctx=ctx)

        assert "error" in result.lower() or "invalid" in result.lower() or "1" in result

    @pytest.mark.anyio
    async def test_validate_pattern_based_net(self):
        """validate_net works on pattern-built nets (not just raw ones)."""
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        gen = session.builder.add_generator("Gen1", interval=5.0)
        machine = session.builder.add_machine("M1", processing_time=10.0)
        session.builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
        session.builder.add_terminator("Exit")

        result = await mock_mcp._tools["validate_net"](ctx=ctx)

        assert result  # any non-empty response is acceptable


# ---------------------------------------------------------------------------
# list_elements
# ---------------------------------------------------------------------------


class TestListElementsTool:
    @pytest.mark.anyio
    async def test_list_elements_empty_net(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, _ = await _make_ctx()

        result = await mock_mcp._tools["list_elements"](ctx=ctx)

        assert "No network" in result or "places" in result.lower()

    @pytest.mark.anyio
    async def test_list_elements_shows_place_name_and_id(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("MyPlace", tokens=3)

        result = await mock_mcp._tools["list_elements"](ctx=ctx)

        assert "MyPlace" in result
        assert pid in result

    @pytest.mark.anyio
    async def test_list_elements_shows_transition_name(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        # list_elements requires at least one place to confirm a network exists
        session.builder.add_raw_place("P1")
        session.builder.add_raw_transition("MyTransition", mean_delay=7.0)

        result = await mock_mcp._tools["list_elements"](ctx=ctx)

        assert "MyTransition" in result

    @pytest.mark.anyio
    async def test_list_elements_shows_arc(self):
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        pid = session.builder.add_raw_place("P1")
        tid = session.builder.add_raw_transition("T1")
        session.builder.add_raw_arc(pid, tid, weight=2)

        result = await mock_mcp._tools["list_elements"](ctx=ctx)

        assert "P1" in result
        assert "T1" in result

    @pytest.mark.anyio
    async def test_list_elements_pattern_net(self):
        """list_elements exposes IDs from pattern-built nets for downstream editing."""
        mock_mcp = MockFastMCP()
        register_petri_tools(mock_mcp)
        ctx, store = await _make_ctx()
        session = await _get_session(store, ctx)
        session.builder.add_generator("Gen1", interval=5.0)
        session.builder.add_machine("M1", processing_time=10.0)

        result = await mock_mcp._tools["list_elements"](ctx=ctx)

        assert "Gen1" in result
        assert "M1" in result
