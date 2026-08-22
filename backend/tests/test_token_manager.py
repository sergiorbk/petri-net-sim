"""Tests for TokenManager — token counting, truncation, estimation."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.core.agent_config import agent_settings
from src.services.llm.token_manager import TokenManager, get_token_manager


@pytest.fixture
def tm() -> TokenManager:
    return TokenManager()


def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def _ai(text: str) -> AIMessage:
    return AIMessage(content=text)


def _system(text: str) -> SystemMessage:
    return SystemMessage(content=text)


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_empty_string_returns_zero(self, tm):
        assert tm.count_tokens("") == 0

    def test_single_word(self, tm):
        count = tm.count_tokens("hello")
        assert count >= 1

    def test_longer_text_has_more_tokens(self, tm):
        short = tm.count_tokens("hi")
        long = tm.count_tokens("This is a longer sentence with more words in it")
        assert long > short


# ---------------------------------------------------------------------------
# count_message_tokens
# ---------------------------------------------------------------------------


class TestCountMessageTokens:
    def test_human_message_has_overhead(self, tm):
        msg = _human("hello")
        count = tm.count_message_tokens(msg)
        assert count > 0
        assert count >= tm.TOKENS_PER_MESSAGE

    def test_ai_message_counted(self, tm):
        msg = _ai("Here is my response")
        count = tm.count_message_tokens(msg)
        assert count > 0

    def test_system_message_counted(self, tm):
        msg = _system("You are a helpful assistant")
        count = tm.count_message_tokens(msg)
        assert count > 0

    def test_tool_message_counted(self, tm):
        msg = ToolMessage(content="tool result", tool_call_id="call_123")
        count = tm.count_message_tokens(msg)
        assert count > 0

    def test_multimodal_list_content(self, tm):
        msg = HumanMessage(content=[{"type": "text", "text": "hello world"}])
        count = tm.count_message_tokens(msg)
        assert count > 0

    def test_multimodal_string_in_list(self, tm):
        msg = HumanMessage(content=["hello", "world"])
        count = tm.count_message_tokens(msg)
        assert count > 0


# ---------------------------------------------------------------------------
# count_messages_tokens
# ---------------------------------------------------------------------------


class TestCountMessagesTokens:
    def test_empty_list_returns_priming_tokens(self, tm):
        # Always adds 3 for reply priming
        assert tm.count_messages_tokens([]) == 3

    def test_accumulates_across_messages(self, tm):
        msgs = [_human("hello"), _ai("world")]
        total = tm.count_messages_tokens(msgs)
        assert total > 3

    def test_more_messages_more_tokens(self, tm):
        short = tm.count_messages_tokens([_human("hi")])
        long = tm.count_messages_tokens([_human("hi")] * 5)
        assert long > short


# ---------------------------------------------------------------------------
# truncate_messages
# ---------------------------------------------------------------------------


class TestTruncateMessages:
    def test_empty_returns_empty(self, tm):
        assert tm.truncate_messages([]) == []

    def test_within_limit_returns_all(self, tm):
        msgs = [_human("hello"), _ai("world")]
        result = tm.truncate_messages(msgs, max_tokens=10000)
        assert len(result) == 2

    def test_truncates_oldest_first(self, tm):
        msgs = [_human(f"message number {i} " * 20) for i in range(20)]
        result = tm.truncate_messages(msgs, max_tokens=100)
        assert len(result) < len(msgs)
        # Newest messages should be preserved
        if result:
            assert result[-1].content == msgs[-1].content

    def test_preserves_system_messages(self, tm):
        msgs = [_system("System prompt"), _human("old"), _human("old2"), _human("new")]
        result = tm.truncate_messages(msgs, max_tokens=100, preserve_system=True)
        system_msgs = [m for m in result if isinstance(m, SystemMessage)]
        assert len(system_msgs) >= 1

    def test_no_preserve_system_does_not_separate(self, tm):
        msgs = [_system("sys"), _human("u1"), _human("u2")]
        result = tm.truncate_messages(msgs, max_tokens=10000, preserve_system=False)
        assert len(result) == 3

    def test_uses_default_max_tokens_when_none(self, tm):
        msgs = [_human("hello")]
        result = tm.truncate_messages(msgs, max_tokens=None)
        assert isinstance(result, list)

    def test_system_exceeds_limit_returns_system_only(self, tm):
        # Very small limit — even system messages exceed it
        long_system = _system("system " * 200)
        msgs = [long_system, _human("user")]
        result = tm.truncate_messages(msgs, max_tokens=1, preserve_system=True)
        system_msgs = [m for m in result if isinstance(m, SystemMessage)]
        assert len(system_msgs) >= 1

    def test_truncation_stops_when_budget_exceeded(self, tm):
        # Many long messages, tight budget — only newest fits
        msgs = [_human("word " * 50) for _ in range(20)]
        result = tm.truncate_messages(msgs, max_tokens=50, preserve_system=False)
        assert len(result) < 20


# ---------------------------------------------------------------------------
# estimate_response_tokens
# ---------------------------------------------------------------------------


class TestEstimateResponseTokens:
    def test_reports_the_room_left_under_a_given_ceiling(self, tm):
        assert tm.estimate_response_tokens(10, max_completion_tokens=100) == 90

    def test_a_prompt_past_the_ceiling_leaves_nothing(self, tm):
        assert tm.estimate_response_tokens(999999, max_completion_tokens=100) == 0

    def test_no_ceiling_anywhere_means_there_is_none_to_report(self, tm, monkeypatch):
        """This app imposes no output ceiling, so a model may answer up to
        its own maximum. "How much is left" is a question about a limit;
        with no limit the answer is that there is not one, not a number big
        enough to be mistaken for one."""
        monkeypatch.setattr(agent_settings, "AGENT_LLM_MAX_TOKENS", None)
        assert tm.estimate_response_tokens(100) is None

    def test_a_configured_ceiling_is_still_used(self, tm, monkeypatch):
        monkeypatch.setattr(agent_settings, "AGENT_LLM_MAX_TOKENS", 500)
        assert tm.estimate_response_tokens(100) == 400


# ---------------------------------------------------------------------------
# get_token_manager singleton
# ---------------------------------------------------------------------------


class TestGetTokenManager:
    def test_returns_token_manager_instance(self):
        tm = get_token_manager()
        assert isinstance(tm, TokenManager)

    def test_returns_same_instance(self):
        tm1 = get_token_manager()
        tm2 = get_token_manager()
        assert tm1 is tm2


class TestBlockContentIsCounted:
    """A message's content is a plain string or a list of content blocks,
    and which one it is depends on the model rather than on anything this
    app does. Handing a block list to tiktoken raises a bare "expected
    string or buffer" -- which is what killed a chat turn AFTER a
    successful API call, with the reply already paid for and the caller
    left waiting -- so the shape is normalised before counting."""

    def test_blocks_count_as_their_text_does(self, tm: TokenManager):
        blocks = [
            {"type": "thinking", "thinking": "some private reasoning"},
            {"type": "text", "text": "Hello there"},
        ]
        assert tm.count_tokens(blocks) == tm.count_tokens("Hello there")

    def test_thinking_and_tool_use_do_not_count(self, tm: TokenManager):
        """They are not part of the visible answer, so they are not part of
        its length either."""
        blocks = [
            {"type": "thinking", "thinking": "x" * 500},
            {"type": "tool_use", "id": "t1", "name": "add_place", "input": {}},
        ]
        assert tm.count_tokens(blocks) == 0

    def test_absent_content_counts_as_nothing(self, tm: TokenManager):
        assert tm.count_tokens(None) == 0


class TestContentToText:
    def test_a_plain_string_passes_through(self):
        from src.services.llm.message_content import content_to_text

        assert content_to_text("already text") == "already text"

    def test_text_blocks_are_joined_in_order(self):
        from src.services.llm.message_content import content_to_text

        assert content_to_text([
            {"type": "text", "text": "one "},
            {"type": "thinking", "thinking": "skipped"},
            {"type": "text", "text": "two"},
        ]) == "one two"

    def test_bare_strings_in_a_list_are_kept(self):
        from src.services.llm.message_content import content_to_text

        assert content_to_text(["a", "b"]) == "ab"

    def test_the_chat_service_shares_this_one_definition(self):
        """The service had its own copy and the agent had none, which is
        exactly why one side coped with blocks and the other crashed."""
        from src.services.chat.openai_chat_service import _extract_text
        from src.services.llm.message_content import content_to_text

        assert _extract_text is content_to_text
