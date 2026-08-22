"""Tests for OpenAIChatService streaming and content extraction."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from src.core.agent_config import LLMProvider
from src.core.config import settings
from src.openai_api.v1.schemas.chat import ChatMessage
from src.services.chat.openai_chat_service import (
    OpenAIChatService,
    _ensure_object_style,
    _extract_text,
    _truncate_tool_output,
)
from src.services.llm.credentials import LLMCredentials
from src.services.petri.session import PetriNetSession
from src.services.llm.credentials_resolver import ResolvedCredentials


def _fake_resolved() -> ResolvedCredentials:
    return ResolvedCredentials(
        credentials=LLMCredentials(
            provider=LLMProvider.OPENAI,
            api_key="sk-test",
            model="gpt-4o",
        ),
        source="byok",
        profile_id=None,
        profile_name=None,
    )


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_extract_text_string_passthrough():
    assert _extract_text("hello") == "hello"


def test_extract_text_none_and_empty():
    assert _extract_text(None) == ""
    assert _extract_text([]) == ""


def test_extract_text_block_list_keeps_only_text_blocks():
    content = [
        {"type": "text", "text": "Let me think."},
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "create_network",
            "input": {"name": "X"},
        },
        {"type": "text", "text": " Done."},
    ]
    assert _extract_text(content) == "Let me think. Done."


def test_extract_text_rejects_python_repr_leak():
    """A raw list must NEVER stringify into Python repr garbage."""
    content = [
        {"type": "text", "text": "visible"},
        {"type": "tool_use", "id": "t1", "name": "foo", "input": {}},
    ]
    result = _extract_text(content)
    assert "tool_use" not in result
    assert "{'type'" not in result
    assert result == "visible"


def test_extract_text_accepts_string_blocks():
    # Older LangChain variants occasionally yield plain strings inside the list.
    assert _extract_text(["a", "b"]) == "ab"


def test_truncate_tool_output_short_passthrough():
    assert _truncate_tool_output("short") == "short"


def test_truncate_tool_output_caps_long_text():
    long = "x" * 2500
    out = _truncate_tool_output(long, limit=2000)
    assert out.endswith("... (truncated)")
    assert len(out) < len(long)


# ---------------------------------------------------------------------------
# _ensure_object_style: deterministic Object-mode fallback framing
# ---------------------------------------------------------------------------


def _flat_net_data(name: str = "PetriNet") -> dict:
    return {
        "name": name,
        "places": [{"id": "p1", "name": "P1", "tokens": 1, "graphics": {"x": 0, "y": 0}}],
        "transitions": [
            {
                "id": "t1", "name": "T1", "priority": 1, "distribution": None,
                "mean_delay": 0.0, "standard_deviation": 0.0, "probability": None,
                "graphics": {"x": 100, "y": 0},
            }
        ],
        "arcs": [{"id": "arc1", "source_id": "p1", "target_id": "t1", "weight": 1, "arc_type": "NORMAL"}],
    }


def _patterned_net_data() -> dict:
    """A flat net built the way the agent actually builds one: out of
    patterns, whose names and membership the builder records."""
    session = PetriNetSession()
    builder = session.builder
    gen = builder.add_generator("Arrivals", interval=10.0)
    exit_ = builder.add_terminator("Counter")
    builder.connect(gen.interface.output_place_id, exit_.interface.input_place_id)
    return session.to_net_data()


def test_ensure_object_style_frames_each_pattern_in_object_mode():
    framed = _ensure_object_style(_patterned_net_data(), "object")
    assert [o["name"] for o in framed["objects"]] == ["Arrivals", "Counter"]
    assert all(p.get("objectId") for p in framed["places"])
    assert all(t.get("objectId") for t in framed["transitions"])


def test_ensure_object_style_never_wraps_the_whole_net_in_one_object():
    """The behaviour this replaced: one frame round everything says nothing
    a flat net did not already say."""
    framed = _ensure_object_style(_patterned_net_data(), "object")
    assert len(framed["objects"]) > 1


def test_ensure_object_style_leaves_a_pattern_less_net_flat():
    """No patterns means no blocks to separate, so there is nothing
    honest to frame -- returned unchanged, by identity."""
    net_data = _flat_net_data()
    assert _ensure_object_style(net_data, "object") is net_data


def test_ensure_object_style_is_a_noop_in_classical_net_style():
    net_data = _flat_net_data()
    assert _ensure_object_style(net_data, "classical") is net_data


def test_ensure_object_style_is_a_noop_on_empty_net_data():
    assert _ensure_object_style({}, "object") == {}


def test_ensure_object_style_preserves_the_pnml_export_side_channel():
    """A non-standard key tool_node merges into net_data, which
    PetriNetSession.from_net_data would reject as an unexpected kwarg --
    it has to be lifted out and put back around the framing pass."""
    net_data = _patterned_net_data()
    net_data["_last_pnml_export"] = "<pnml>...</pnml>"
    framed = _ensure_object_style(net_data, "object")
    assert framed["_last_pnml_export"] == "<pnml>...</pnml>"
    assert len(framed["objects"]) == 2


def test_ensure_object_style_leaves_an_already_composed_net_alone():
    net_data = _flat_net_data()
    net_data["places"][0]["objectId"] = "obj0"
    net_data["transitions"][0]["objectId"] = "obj0"
    net_data["objects"] = [
        {"id": "obj0", "name": "Existing", "priority": 0,
         "graphics": {"x": 0, "y": 0, "width": 200, "height": 150}},
    ]
    assert _ensure_object_style(net_data, "object") is net_data


# ---------------------------------------------------------------------------
# Streaming loop tests — mock the graph and session dependencies
# ---------------------------------------------------------------------------


def _sse_payloads(raw: list[str]) -> list[dict]:
    """Parse SSE frames yielded by complete_stream into JSON dicts.

    Each frame starts with ``data: `` and ends with a blank line. The DONE
    sentinel is skipped. Returns a list of parsed chunk bodies in order.
    """
    out: list[dict] = []
    for line in raw:
        stripped = line.strip()
        if not stripped or stripped == "data: [DONE]":
            continue
        if stripped.startswith("data: "):
            body = stripped[len("data: ") :]
            out.append(json.loads(body))
    return out


async def _run_stream(service: OpenAIChatService, messages: list[ChatMessage]) -> list[dict]:
    raw: list[str] = []
    async for frame in service.complete_stream(
        messages=messages,
        user_id=uuid4(),
        resolved=_fake_resolved(),
    ):
        raw.append(frame)
    return _sse_payloads(raw)


def _make_service_with_fake_graph(async_session, graph_updates: list[dict]) -> OpenAIChatService:
    """Construct a service and stub out all external dependencies."""

    service = OpenAIChatService(async_session)

    # Stub session_service — don't hit DB
    service._session_service = MagicMock()
    service._session_service.get_or_create = AsyncMock(return_value=None)
    service._session_service.restore_net_data = AsyncMock(return_value={})
    service._session_service.save_net_data = AsyncMock(return_value=None)
    service._session_service.set_title_if_empty = AsyncMock(return_value=None)
    service._session_service.save_snapshot_and_net = AsyncMock(return_value=None)
    fake_repo = MagicMock()
    fake_repo.update_llm_credential = AsyncMock(return_value=None)
    service._session_service.session_repository = fake_repo

    # Stub memory_service — identity passthrough
    service._memory_service = MagicMock()
    service._memory_service.apply_context_window = lambda msgs: msgs

    # Stub token_manager
    service._token_manager = MagicMock()
    service._token_manager.count_tokens = lambda text: len(text.split())
    service._token_manager.count_messages_tokens = lambda msgs: 0

    # Stub graph.astream to yield the provided updates, in the shape a
    # multi-mode stream really has: LangGraph tags every item with the mode
    # it came from once stream_mode is a list, and the service asks for
    # ["updates", "messages"] so a model's tokens can arrive while a node is
    # still running. These fixtures exercise the "updates" half; the token
    # half has its own tests below.
    #
    # Accepts (and ignores) `config` so the D4 recursion_limit kwarg doesn't
    # break the fake -- test_stream_passes_recursion_limit_config below
    # asserts on it via a separate spy instead of this shared fixture.
    async def _astream(
        state: Any,
        stream_mode: Any = "updates",
        config: dict | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        for update in graph_updates:
            yield ("updates", update)

    fake_graph = MagicMock()
    fake_graph.astream = _astream
    service._graph = fake_graph

    return service


@pytest.mark.asyncio
async def test_stream_emits_text_blocks_as_content(session):
    """Plain text inside Anthropic content blocks streams as delta.content."""
    updates = [
        {
            "respond": {
                "messages": [
                    AIMessage(content=[{"type": "text", "text": "Hello world"}])
                ]
            }
        }
    ]
    service = _make_service_with_fake_graph(session, updates)

    frames = await _run_stream(service, [ChatMessage(role="user", content="hi")])

    content_chunks = [
        c["choices"][0]["delta"].get("content")
        for c in frames
        if c.get("choices") and c["choices"][0]["delta"].get("content")
    ]
    joined = "".join(content_chunks)
    assert "Hello world" in joined
    # Must never leak Python repr
    assert "'type'" not in joined
    assert "tool_use" not in joined


@pytest.mark.asyncio
async def test_stream_emits_agent_event_for_tool_call(session):
    """AIMessage.tool_calls produces an agent_event chunk with type=tool_call."""
    ai = AIMessage(
        content=[
            {"type": "text", "text": "Creating the net"},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "create_network",
                "input": {"name": "X"},
            },
        ],
        tool_calls=[
            {"id": "toolu_1", "name": "create_network", "args": {"name": "X"}}
        ],
    )
    updates = [{"respond": {"messages": [ai]}}]
    service = _make_service_with_fake_graph(session, updates)

    frames = await _run_stream(service, [ChatMessage(role="user", content="build")])

    events = [
        c["choices"][0]["delta"]["agent_event"]
        for c in frames
        if c.get("choices")
        and c["choices"][0]["delta"].get("agent_event")
    ]
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "tool_call"
    assert ev["id"] == "toolu_1"
    assert ev["name"] == "create_network"
    assert ev["input"] == {"name": "X"}
    assert ev["status"] == "running"


@pytest.mark.asyncio
async def test_stream_emits_tool_result_event(session):
    """ToolMessage produces an agent_event chunk with type=tool_result."""
    updates = [
        {
            "execute_tool": {
                "messages": [
                    ToolMessage(
                        content="Created network with id p1",
                        tool_call_id="toolu_1",
                    )
                ]
            }
        }
    ]
    service = _make_service_with_fake_graph(session, updates)

    frames = await _run_stream(service, [ChatMessage(role="user", content="build")])

    events = [
        c["choices"][0]["delta"]["agent_event"]
        for c in frames
        if c.get("choices")
        and c["choices"][0]["delta"].get("agent_event")
    ]
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "tool_result"
    assert ev["id"] == "toolu_1"
    assert ev["status"] == "success"
    assert "Created network" in ev["output"]


@pytest.mark.asyncio
async def test_stream_never_leaks_python_repr_on_list_content(session):
    """Regression: previously ``str(list_of_blocks)`` leaked repr to clients."""
    ai = AIMessage(
        content=[
            {"type": "text", "text": "visible"},
            {
                "type": "tool_use",
                "id": "t1",
                "name": "foo",
                "input": {"k": 1},
            },
        ],
        tool_calls=[{"id": "t1", "name": "foo", "args": {"k": 1}}],
    )
    updates = [{"respond": {"messages": [ai]}}]
    service = _make_service_with_fake_graph(session, updates)

    frames = await _run_stream(service, [ChatMessage(role="user", content="x")])

    for chunk in frames:
        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
        content = delta.get("content") or ""
        assert "'type'" not in content
        assert "tool_use" not in content
        assert "{'id'" not in content


def _make_service_streaming(async_session, items: list[tuple[str, Any]]) -> OpenAIChatService:
    """Same stubs, but the fake graph yields whatever mixed-mode sequence a
    test hands it -- token chunks and node updates interleaved, as they
    really arrive."""
    service = _make_service_with_fake_graph(async_session, [])

    async def _astream(state: Any, stream_mode: Any = "updates", config: dict | None = None):
        for item in items:
            yield item

    fake_graph = MagicMock()
    fake_graph.astream = _astream
    service._graph = fake_graph
    return service


def _content_of(frames: list[dict]) -> str:
    return "".join(
        c["choices"][0]["delta"].get("content") or ""
        for c in frames
        if c.get("choices")
    )


class TestTokensArriveWhileTheNodeIsStillRunning:
    """A node update only fires once the node has FINISHED, so a model that
    thinks for a minute and then emits several tool calls delivered all of
    them at once after a minute of nothing on screen. Token chunks are the
    only thing that can fill that minute, so the stream asks for both."""

    @pytest.mark.asyncio
    async def test_token_chunks_reach_the_client_as_they_arrive(self, session):
        service = _make_service_streaming(session, [
            ("messages", (AIMessageChunk(content="Hel"), {})),
            ("messages", (AIMessageChunk(content="lo"), {})),
        ])

        frames = await _run_stream(service, [ChatMessage(role="user", content="hi")])

        assert _content_of(frames) == "Hello"

    @pytest.mark.asyncio
    async def test_the_finished_message_does_not_repeat_what_streamed(self, session):
        """The node update carries the whole answer as well; sending it
        again would show it twice."""
        service = _make_service_streaming(session, [
            ("messages", (AIMessageChunk(content="Hello "), {})),
            ("messages", (AIMessageChunk(content="world"), {})),
            ("updates", {"respond": {"messages": [AIMessage(content="Hello world")]}}),
        ])

        frames = await _run_stream(service, [ChatMessage(role="user", content="hi")])

        assert _content_of(frames) == "Hello world"

    @pytest.mark.asyncio
    async def test_a_late_addition_after_the_tokens_still_gets_through(self, session):
        service = _make_service_streaming(session, [
            ("messages", (AIMessageChunk(content="Hello"), {})),
            ("updates", {"respond": {"messages": [AIMessage(content="Hello world")]}}),
        ])

        frames = await _run_stream(service, [ChatMessage(role="user", content="hi")])

        assert _content_of(frames) == "Hello world"

    @pytest.mark.asyncio
    async def test_a_provider_that_never_streamed_still_gets_its_answer_out(self, session):
        """Nothing streamed means the whole text is still owed, which is the
        path every non-streaming provider takes."""
        service = _make_service_streaming(session, [
            ("updates", {"respond": {"messages": [AIMessage(content="Hello world")]}}),
        ])

        frames = await _run_stream(service, [ChatMessage(role="user", content="hi")])

        assert _content_of(frames) == "Hello world"


# ---------------------------------------------------------------------------
# D4: explicit, configurable recursion_limit at both ainvoke/astream sites
# ---------------------------------------------------------------------------


def _make_service_for_complete(async_session, ainvoke_result: dict) -> OpenAIChatService:
    """Construct a service with a fake `_graph.ainvoke`, stubbing the same
    external dependencies `_make_service_with_fake_graph` stubs for astream."""
    service = OpenAIChatService(async_session)

    service._session_service = MagicMock()
    service._session_service.get_or_create = AsyncMock(return_value=None)
    service._session_service.restore_net_data = AsyncMock(return_value={})
    service._session_service.save_net_data = AsyncMock(return_value=None)
    service._session_service.set_title_if_empty = AsyncMock(return_value=None)
    fake_repo = MagicMock()
    fake_repo.update_llm_credential = AsyncMock(return_value=None)
    service._session_service.session_repository = fake_repo

    service._memory_service = MagicMock()
    service._memory_service.apply_context_window = lambda msgs: msgs

    service._token_manager = MagicMock()
    service._token_manager.count_tokens = lambda text: len(text.split())
    service._token_manager.count_messages_tokens = lambda msgs: 0

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(return_value=ainvoke_result)
    service._graph = fake_graph

    return service


@pytest.mark.asyncio
async def test_complete_passes_recursion_limit_config(session):
    """.complete() (the non-streaming path) must call ainvoke with an
    explicit recursion_limit, not rely on LangGraph's own default."""
    human = HumanMessage(content="hi")
    ai = AIMessage(content="Done")
    service = _make_service_for_complete(session, {"messages": [human, ai], "net_data": {}})

    await service.complete(
        messages=[ChatMessage(role="user", content="hi")],
        user_id=uuid4(),
        resolved=_fake_resolved(),
    )

    service._graph.ainvoke.assert_awaited_once()
    _, kwargs = service._graph.ainvoke.await_args
    assert kwargs.get("config") == {"recursion_limit": settings.AGENT_RECURSION_LIMIT}


@pytest.mark.asyncio
async def test_stream_passes_recursion_limit_config(session):
    """.complete_stream() (the streaming path) must pass the same explicit
    recursion_limit to astream."""
    seen: dict[str, Any] = {}

    async def _astream(state: Any, stream_mode: str = "updates", config: dict | None = None):
        seen["config"] = config
        return
        yield  # pragma: no cover - makes this an async generator

    service = _make_service_with_fake_graph(session, [])
    service._graph.astream = _astream

    await _run_stream(service, [ChatMessage(role="user", content="hi")])

    assert seen["config"] == {"recursion_limit": settings.AGENT_RECURSION_LIMIT}


def test_default_recursion_limit_is_100():
    """Raised from LangGraph's own implicit default of 25 (~12 tool calls)
    to 100 (~50) -- Object net-style mode's create_object/set_active_object/
    link_objects overhead per subsystem was routinely exhausting 25 before
    a multi-object composed model reached validate_model. See
    AGENT_RECURSION_LIMIT's own comment in core/config.py."""
    assert settings.AGENT_RECURSION_LIMIT == 100
