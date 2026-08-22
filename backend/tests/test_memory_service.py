"""Tests for MemoryService — context windowing, stats, summarization."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.core.agent_config import MemoryStrategy
from src.services.chat.memory_service import MemoryService


def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def _ai(text: str) -> AIMessage:
    return AIMessage(content=text)


def _system(text: str) -> SystemMessage:
    return SystemMessage(content=text)


def _make_svc(
    strategy: MemoryStrategy = MemoryStrategy.SLIDING_WINDOW,
    max_tokens: int = 1000,
    max_messages: int = 40,
) -> MemoryService:
    return MemoryService(
        strategy=strategy,
        max_tokens=max_tokens,
        max_messages=max_messages,
        summarization_threshold=5,
    )


# ---------------------------------------------------------------------------
# apply_context_window
# ---------------------------------------------------------------------------


class TestApplyContextWindow:
    def test_empty_messages_returns_empty(self):
        svc = _make_svc()
        result = svc.apply_context_window([])
        assert result == []

    def test_sliding_window_strategy_dispatches(self):
        svc = _make_svc(MemoryStrategy.SLIDING_WINDOW, max_tokens=200)
        msgs = [_human(f"msg {i}") for i in range(10)]
        result = svc.apply_context_window(msgs)
        assert len(result) <= len(msgs)

    def test_token_window_strategy_dispatches(self):
        svc = _make_svc(MemoryStrategy.TOKEN_WINDOW, max_tokens=500)
        msgs = [_human("hello"), _ai("world")]
        result = svc.apply_context_window(msgs)
        assert isinstance(result, list)

    def test_summarization_strategy_dispatches(self):
        svc = _make_svc(MemoryStrategy.SUMMARIZATION, max_tokens=500)
        # Below threshold → returns messages as-is
        msgs = [_human("msg1"), _ai("reply1")]
        result = svc.apply_context_window(msgs)
        assert len(result) == 2

    def test_unknown_strategy_returns_messages(self):
        svc = _make_svc()
        svc._strategy = None  # force the fallthrough branch
        msgs = [_human("a"), _ai("b")]
        result = svc.apply_context_window(msgs)
        assert result == msgs


# ---------------------------------------------------------------------------
# _apply_sliding_window
# ---------------------------------------------------------------------------


class TestApplySlidingWindow:
    def test_preserves_system_messages(self):
        svc = _make_svc(max_tokens=100)
        msgs = [_system("System"), _human("a"), _ai("b")]
        result = svc._apply_sliding_window(msgs)
        assert isinstance(result[0], SystemMessage)

    def test_truncates_when_over_window(self):
        """The window is a message count now, stated as one. It used to be
        max_tokens divided by a hardcoded "assume 100 tokens per message",
        so the knob said tokens and meant messages."""
        svc = _make_svc(max_messages=1)
        msgs = [_human(f"msg{i}") for i in range(5)]
        result = svc._apply_sliding_window(msgs)
        assert len(result) == 1
        assert result[0].content == "msg4"

    def test_the_token_setting_no_longer_moves_this_window(self):
        """Proof the two knobs came apart: a tiny token budget leaves the
        message window alone, and only TOKEN_WINDOW counts tokens."""
        svc = _make_svc(max_tokens=1, max_messages=3)
        msgs = [_human(f"msg{i}") for i in range(5)]
        assert len(svc._apply_sliding_window(msgs)) == 3

    def test_keeps_all_when_within_window(self):
        svc = _make_svc(max_messages=50)
        msgs = [_human("a"), _ai("b"), _human("c")]
        result = svc._apply_sliding_window(msgs)
        assert len(result) == 3

    def test_system_plus_window(self):
        # window=1, 1 system + 1 from last
        svc = _make_svc(max_messages=1)
        msgs = [_system("Sys"), _human("old"), _ai("old reply"), _human("new")]
        result = svc._apply_sliding_window(msgs)
        assert isinstance(result[0], SystemMessage)
        assert result[-1].content == "new"


# ---------------------------------------------------------------------------
# _apply_summarization
# ---------------------------------------------------------------------------


class TestApplySummarization:
    def test_below_threshold_returns_unchanged(self):
        svc = _make_svc(MemoryStrategy.SUMMARIZATION)
        msgs = [_human("a"), _ai("b")]  # below threshold=5
        result = svc._apply_summarization(msgs)
        assert len(result) == 2

    def test_above_threshold_falls_back_to_token_window(self):
        svc = _make_svc(MemoryStrategy.SUMMARIZATION, max_tokens=5000)
        msgs = [_human(f"msg{i}") for i in range(10)]  # above threshold=5
        result = svc._apply_summarization(msgs)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# get_context_stats
# ---------------------------------------------------------------------------


class TestGetContextStats:
    def test_returns_correct_role_counts(self):
        svc = _make_svc()
        msgs = [_system("sys"), _human("u1"), _human("u2"), _ai("a1")]
        stats = svc.get_context_stats(msgs)

        assert stats["role_counts"]["system"] == 1
        assert stats["role_counts"]["user"] == 2
        assert stats["role_counts"]["assistant"] == 1
        assert stats["message_count"] == 4

    def test_total_tokens_is_positive(self):
        svc = _make_svc()
        msgs = [_human("hello"), _ai("world")]
        stats = svc.get_context_stats(msgs)
        assert stats["total_tokens"] > 0

    def test_tokens_remaining_positive(self):
        svc = _make_svc(max_tokens=10000)
        msgs = [_human("short")]
        stats = svc.get_context_stats(msgs)
        assert stats["tokens_remaining"] > 0

    def test_empty_messages(self):
        svc = _make_svc()
        stats = svc.get_context_stats([])
        assert stats["message_count"] == 0
        assert stats["role_counts"]["user"] == 0


# ---------------------------------------------------------------------------
# needs_summarization
# ---------------------------------------------------------------------------


class TestNeedsSummarization:
    def test_returns_false_for_non_summarization_strategy(self):
        svc = _make_svc(MemoryStrategy.SLIDING_WINDOW)
        msgs = [_human(f"m{i}") for i in range(20)]
        assert svc.needs_summarization(msgs) is False

    def test_returns_false_below_threshold(self):
        svc = _make_svc(MemoryStrategy.SUMMARIZATION)
        msgs = [_human("a"), _ai("b")]
        assert svc.needs_summarization(msgs) is False

    def test_returns_true_above_threshold(self):
        svc = _make_svc(MemoryStrategy.SUMMARIZATION)
        msgs = [_human(f"m{i}") for i in range(10)]  # > threshold=5
        assert svc.needs_summarization(msgs) is True


# ---------------------------------------------------------------------------
# create_summary
# ---------------------------------------------------------------------------


class TestCreateSummary:
    @pytest.mark.anyio
    async def test_returns_empty_for_no_messages(self):
        svc = _make_svc()
        mock_generate = AsyncMock(return_value="summary")
        result = await svc.create_summary([], mock_generate)
        assert result == ""

    @pytest.mark.anyio
    async def test_calls_llm_and_returns_summary(self):
        svc = _make_svc()
        msgs = [_human("Tell me about petri nets"), _ai("Petri nets are...")]
        mock_generate = AsyncMock(return_value="A brief summary.")

        result = await svc.create_summary(msgs, mock_generate)

        assert isinstance(result, str)
        mock_generate.assert_called_once()


# ---------------------------------------------------------------------------
# get_context_stats — tool message role
# ---------------------------------------------------------------------------


class TestGetContextStatsTool:
    def test_tool_message_counted_as_tool(self):
        svc = _make_svc()
        msgs = [ToolMessage(content="result", tool_call_id="call_1")]
        stats = svc.get_context_stats(msgs)
        assert stats["role_counts"]["tool"] == 1

    def test_format_messages_with_system_and_tool(self):
        svc = _make_svc()
        msgs = [
            _system("sys"),
            _human("hello"),
            ToolMessage(content="tool result", tool_call_id="call_1"),
        ]
        # _format_messages_for_summary skips system, counts tool
        formatted = svc._format_messages_for_summary(msgs)
        assert "hello" in formatted
        assert "Tool" in formatted
        # system messages should NOT appear in the formatted text body
        assert "sys" not in formatted
