"""chat_node against the content shapes real models answer with.

A newer Claude model answers with a LIST of content blocks where older
ones answered with a string. The turn that surfaced this got a perfectly
successful API call and then died inside our own handling of the reply,
so the caller saw no answer at all and no error either -- the reply was
paid for and thrown away.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.core.agent_config import LLMProvider
from src.services.agent.nodes.chat_node import chat_node
from src.services.llm.credentials import LLMCredentials


def _state(messages: list) -> dict:
    return {
        "messages": messages,
        "conversation_id": "c1",
        "token_count": 0,
        "credentials": LLMCredentials(
            provider=LLMProvider.ANTHROPIC, api_key="sk-test", model="claude-sonnet-5"
        ),
        "context": {},
        "net_data": {},
    }


async def _run(response: AIMessage) -> dict:
    """Drive chat_node with a provider whose model returns `response`."""
    bound = MagicMock()
    bound.ainvoke = AsyncMock(return_value=response)
    model = MagicMock()
    model.bind_tools.return_value = bound

    provider = MagicMock()
    provider.provider_name = "anthropic"
    provider.model_name = "claude-sonnet-5"
    provider.get_chat_model.return_value = model

    factory = MagicMock()
    factory.for_credentials = AsyncMock(return_value=provider)

    with patch("src.services.agent.nodes.chat_node.get_llm_factory", return_value=factory):
        return await chat_node(_state([HumanMessage(content="build a net")]))


class TestBlockContentReply:
    @pytest.mark.asyncio
    async def test_a_reply_in_blocks_does_not_fail_the_turn(self):
        result = await _run(AIMessage(content=[
            {"type": "thinking", "thinking": "private reasoning"},
            {"type": "text", "text": "Here is your net."},
        ]))

        assert result["error"] is None
        assert result["next_action"] == "end"

    @pytest.mark.asyncio
    async def test_the_reply_is_counted_by_its_text(self):
        """It used to be counted by handing the raw blocks to tiktoken,
        which raised "expected string or buffer"."""
        result = await _run(AIMessage(content=[
            {"type": "text", "text": "Here is your net."},
        ]))

        assert result["token_count"] > 0

    @pytest.mark.asyncio
    async def test_the_blocks_themselves_are_kept_on_the_message(self):
        """They are what the model actually said; flattening them here
        would throw away everything that is not visible text."""
        blocks = [
            {"type": "thinking", "thinking": "private reasoning"},
            {"type": "text", "text": "Here is your net."},
        ]
        result = await _run(AIMessage(content=blocks))

        assert result["messages"][0].content == blocks

    @pytest.mark.asyncio
    async def test_a_plain_string_reply_still_works(self):
        result = await _run(AIMessage(content="Here is your net."))

        assert result["error"] is None
        assert result["messages"][0].content == "Here is your net."
        assert result["token_count"] > 0


class TestReplyWithNothingInIt:
    """A successful API call can still say nothing usable. Passing that on
    as an ordinary empty answer closed the stream with no content and no
    error, which reaches the user as a request that never came back --
    silence being the one response nobody can act on."""

    @staticmethod
    def _reply(blocks: list, stop_reason: str) -> AIMessage:
        message = AIMessage(content=blocks)
        message.response_metadata = {"stop_reason": stop_reason}
        return message

    @pytest.mark.asyncio
    async def test_a_budget_spent_on_thinking_says_so(self):
        """A model that reasons before answering spends the same output
        allowance on thinking; once it is gone there is nothing left to
        answer with. The fix is a setting, so the message names it."""
        result = await _run(self._reply(
            [{"type": "thinking", "thinking": "at length"}], "max_tokens"
        ))

        assert result["next_action"] == "end"
        assert "max_tokens" in result["error"]
        assert "AGENT_LLM_MAX_TOKENS" in result["error"]

    @pytest.mark.asyncio
    async def test_any_other_empty_reply_still_names_its_reason(self):
        result = await _run(self._reply([], "end_turn"))

        assert "end_turn" in result["error"]

    @pytest.mark.asyncio
    async def test_a_tool_call_without_text_is_not_an_empty_reply(self):
        """Answering with only a tool_use block is ordinary and must not be
        mistaken for having said nothing."""
        message = AIMessage(
            content=[{"type": "tool_use", "id": "t1", "name": "create_network", "input": {}}],
            tool_calls=[{"name": "create_network", "args": {}, "id": "t1"}],
        )
        result = await _run(message)

        assert result["error"] is None
        assert result["next_action"] == "use_tool"


class TestSecondChanceOnAnAnswerableRefusal:
    """A refusal that names its own remedy deserves one retry. The provider
    decides whether it can act on the error; the node only offers the
    chance, so it stays ignorant of what any provider can adapt to."""

    @staticmethod
    async def _run_with(provider, responses: list) -> dict:
        """Drive chat_node with a model whose calls return/raise in turn."""
        bound = MagicMock()
        bound.ainvoke = AsyncMock(side_effect=responses)
        model = MagicMock()
        model.bind_tools.return_value = bound
        provider.get_chat_model.return_value = model

        factory = MagicMock()
        factory.for_credentials = AsyncMock(return_value=provider)
        with patch(
            "src.services.agent.nodes.chat_node.get_llm_factory", return_value=factory
        ):
            return await chat_node(_state([HumanMessage(content="build a net")]))

    @pytest.mark.asyncio
    async def test_an_adaptable_refusal_is_retried_and_succeeds(self):
        provider = MagicMock()
        provider.provider_name = "anthropic"
        provider.model_name = "claude-sonnet-5"
        provider.adapt_to_error.return_value = True

        result = await self._run_with(provider, [
            Exception("max_tokens: 64000 > 8192"),
            AIMessage(content="Here is your net."),
        ])

        assert result["error"] is None
        assert result["messages"][0].content == "Here is your net."

    @pytest.mark.asyncio
    async def test_a_refusal_nobody_can_adapt_to_travels_on(self):
        provider = MagicMock()
        provider.provider_name = "anthropic"
        provider.model_name = "claude-sonnet-5"
        provider.adapt_to_error.return_value = False

        result = await self._run_with(provider, [Exception("overloaded_error")])

        assert "overloaded_error" in result["error"]

    @pytest.mark.asyncio
    async def test_the_chance_is_offered_exactly_once(self):
        """A second failure after adapting is the answer, not grounds for
        another round."""
        provider = MagicMock()
        provider.provider_name = "anthropic"
        provider.model_name = "claude-sonnet-5"
        provider.adapt_to_error.return_value = True

        result = await self._run_with(provider, [
            Exception("max_tokens: 64000 > 8192"),
            Exception("still refused"),
        ])

        assert "still refused" in result["error"]
        assert provider.adapt_to_error.call_count == 1
