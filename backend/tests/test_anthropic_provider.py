"""Tests for the Anthropic LLM provider and its prompt caching hook."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from src.core.agent_config import LLMProvider
from src.services.llm.credentials import LLMCredentials
from src.services.llm.providers.anthropic_provider import AnthropicProvider


def _creds(
    api_key: str | None = "sk-ant-test",
    model: str = "claude-haiku-4-5-20251001",
    timeout: float | None = None,
    max_tokens: int | None = None,
    base_url: str | None = None,
) -> LLMCredentials:
    return LLMCredentials(
        provider=LLMProvider.ANTHROPIC,
        api_key=api_key,
        model=model,
        timeout=timeout,
        max_tokens=max_tokens,
        base_url=base_url,
    )


@pytest.mark.asyncio
async def test_initialize_requires_api_key():
    provider = AnthropicProvider(_creds(api_key=None))
    with pytest.raises(ValueError, match="Anthropic API key is required"):
        await provider.initialize()


@pytest.mark.asyncio
async def test_initialize_constructs_chat_model():
    with patch(
        "src.services.llm.providers.anthropic_provider.ChatAnthropic"
    ) as mock_cls:
        mock_cls.return_value = MagicMock()
        provider = AnthropicProvider(
            _creds(
                api_key="sk-ant-test",
                model="claude-haiku-4-5-20251001",
                timeout=60.0,
                max_tokens=2048,
            )
        )
        await provider.initialize()

        assert provider.provider_name == "anthropic"
        assert provider.model_name == "claude-haiku-4-5-20251001"
        assert provider.supports_streaming is True

        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["api_key"] == "sk-ant-test"
        assert kwargs["model"] == "claude-haiku-4-5-20251001"
        assert "temperature" not in kwargs
        assert kwargs["timeout"] == 60.0
        assert kwargs["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_get_chat_model_before_init_raises():
    provider = AnthropicProvider(_creds())
    with pytest.raises(RuntimeError, match="not initialized"):
        provider.get_chat_model()


@pytest.mark.asyncio
async def test_shutdown_clears_state():
    with patch(
        "src.services.llm.providers.anthropic_provider.ChatAnthropic"
    ) as mock_cls:
        mock_cls.return_value = MagicMock()
        provider = AnthropicProvider(_creds())
        await provider.initialize()
        assert provider._initialized is True

        await provider.shutdown()
        assert provider._initialized is False
        with pytest.raises(RuntimeError):
            provider.get_chat_model()


@pytest.mark.asyncio
async def test_generate_delegates_to_chat_model():
    with patch(
        "src.services.llm.providers.anthropic_provider.ChatAnthropic"
    ) as mock_cls:
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value="ok")
        mock_cls.return_value = mock_model

        provider = AnthropicProvider(_creds())
        await provider.initialize()

        msgs = [HumanMessage(content="hi")]
        result = await provider.generate(msgs)

        assert result == "ok"
        mock_model.ainvoke.assert_awaited_once_with(msgs)


@pytest.mark.asyncio
async def test_build_system_message_marks_cache_for_anthropic():
    """chat_node must attach cache_control when provider is Anthropic and caching
    enabled. The net-style note is a SEPARATE, uncached block after the cached
    one -- it varies per conversation and must never be part of what gets
    marked cacheable, or every distinct net_style would need its own cache
    entry (see _build_system_message's docstring)."""
    from src.services.agent.nodes.chat_node import SYSTEM_PROMPT, _build_system_message

    provider = MagicMock()
    provider.provider_name = "anthropic"

    with patch("src.services.agent.nodes.chat_node.agent_settings") as settings:
        settings.ANTHROPIC_PROMPT_CACHING = True
        msg = _build_system_message(provider)

    assert isinstance(msg, SystemMessage)
    assert isinstance(msg.content, list)
    assert len(msg.content) == 2
    cached_block, note_block = msg.content
    assert cached_block["type"] == "text"
    assert cached_block["text"] == SYSTEM_PROMPT
    assert cached_block["cache_control"] == {"type": "ephemeral"}
    assert note_block["type"] == "text"
    assert "cache_control" not in note_block


@pytest.mark.asyncio
async def test_build_system_message_plain_for_openai():
    from src.services.agent.nodes.chat_node import SYSTEM_PROMPT, _build_system_message

    provider = MagicMock()
    provider.provider_name = "openai"

    msg = _build_system_message(provider)
    assert isinstance(msg, SystemMessage)
    assert msg.content.startswith(SYSTEM_PROMPT)


@pytest.mark.asyncio
async def test_build_system_message_plain_when_caching_disabled():
    from src.services.agent.nodes.chat_node import SYSTEM_PROMPT, _build_system_message

    provider = MagicMock()
    provider.provider_name = "anthropic"

    with patch("src.services.agent.nodes.chat_node.agent_settings") as settings:
        settings.ANTHROPIC_PROMPT_CACHING = False
        msg = _build_system_message(provider)

    assert isinstance(msg, SystemMessage)
    assert msg.content.startswith(SYSTEM_PROMPT)


@pytest.mark.asyncio
async def test_build_system_message_net_style_selects_the_matching_note():
    from src.services.agent.nodes.chat_node import _NET_STYLE_NOTES, _build_system_message

    provider = MagicMock()
    provider.provider_name = "openai"

    object_msg = _build_system_message(provider, "object")
    classical_msg = _build_system_message(provider, "classical")
    unknown_msg = _build_system_message(provider, "bogus")

    assert _NET_STYLE_NOTES["object"] in object_msg.content
    assert _NET_STYLE_NOTES["classical"] in classical_msg.content
    assert _NET_STYLE_NOTES["classical"] not in object_msg.content
    # An unrecognized value degrades to the default rather than erroring.
    assert _NET_STYLE_NOTES["object"] in unknown_msg.content


class TestTemperatureIsNeverSent:
    """A growing number of models reject `temperature` outright
    ("temperature is deprecated for this model", HTTP 400), and it was on
    every request: a profile that set none had an operator-level default
    substituted, so switching a working profile to one of those models
    broke every call.

    Nothing here has a reason to set a temperature, so none is sent at
    all. That is a stronger guarantee than "sent only when configured" --
    there is no configuration left that could turn it back on and no model
    this can fail against."""

    @pytest.mark.asyncio
    async def test_the_request_carries_no_temperature(self):
        provider = AnthropicProvider(_creds())
        await provider.initialize()

        payload = provider.get_chat_model()._get_request_payload(
            [HumanMessage(content="hi")]
        )
        assert "temperature" not in payload

    @pytest.mark.asyncio
    async def test_the_chat_model_itself_holds_none(self):
        """Belt and braces: LangChain omits the key when the attribute is
        None, so the attribute is what the omission actually rests on."""
        provider = AnthropicProvider(_creds())
        await provider.initialize()
        assert provider.get_chat_model().temperature is None

    def test_no_credential_field_can_reintroduce_it(self):
        from src.services.llm.credentials import LLMCredentials

        assert "temperature" not in LLMCredentials.model_fields


class TestOutputCeiling:
    """Anthropic's API requires max_tokens, so unlike temperature there is
    no "send none". Left unset it would be LangChain's own 4096, which a
    reasoning model can spend entirely on thinking before it answers -- the
    reply then comes back with no text at all."""

    @pytest.mark.asyncio
    async def test_it_asks_for_the_configured_ceiling_by_default(self):
        from src.core.agent_config import agent_settings

        provider = AnthropicProvider(_creds())
        await provider.initialize()
        assert (
            provider.get_chat_model().max_tokens
            == agent_settings.ANTHROPIC_MAX_OUTPUT_TOKENS
        )

    @pytest.mark.asyncio
    async def test_that_ceiling_is_well_above_langchains_own_default(self):
        from src.core.agent_config import agent_settings

        assert agent_settings.ANTHROPIC_MAX_OUTPUT_TOKENS > 4096

    @pytest.mark.asyncio
    async def test_a_profile_ceiling_still_wins(self):
        provider = AnthropicProvider(_creds(max_tokens=2048))
        await provider.initialize()
        assert provider.get_chat_model().max_tokens == 2048


class TestAdaptingToTheModelsOwnMaximum:
    """Asking for more room than a model allows is refused WITH the number
    it allows, which makes the API the source of truth for a figure that
    would otherwise live in a table and go stale on every model release."""

    _REFUSAL = (
        "Error code: 400 - max_tokens: 64000 > 8192, which is the maximum "
        "allowed number of output tokens for claude-3-5-haiku-20241022"
    )

    @pytest.mark.asyncio
    async def test_it_takes_the_number_from_the_refusal(self):
        provider = AnthropicProvider(_creds())
        await provider.initialize()

        assert provider.adapt_to_error(Exception(self._REFUSAL)) is True
        assert provider.get_chat_model().max_tokens == 8192

    @pytest.mark.asyncio
    async def test_it_only_adapts_once(self):
        """Already at or below what is allowed means this refusal was about
        something else, and retrying would just fail again."""
        provider = AnthropicProvider(_creds())
        await provider.initialize()
        provider.adapt_to_error(Exception(self._REFUSAL))

        assert provider.adapt_to_error(Exception(self._REFUSAL)) is False

    @pytest.mark.asyncio
    async def test_an_unrelated_failure_is_left_alone(self):
        provider = AnthropicProvider(_creds())
        await provider.initialize()

        assert provider.adapt_to_error(Exception("overloaded_error")) is False
        assert provider.get_chat_model().max_tokens is not None

    def test_a_provider_with_nothing_to_adapt_says_so(self):
        """The default answer, and the honest one for a provider that has
        not been taught any."""
        from src.services.llm.providers.base import BaseLLMProvider

        assert BaseLLMProvider.adapt_to_error(MagicMock(), Exception("x")) is False
