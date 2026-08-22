"""Anthropic LLM provider."""

import re
import time
from typing import Any, AsyncIterator

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.agent_config import agent_settings
from src.core.logger import get_logger
from src.services.llm.credentials import LLMCredentials
from src.services.llm.providers.base import BaseLLMProvider

logger = get_logger()


class AnthropicProvider(BaseLLMProvider):
    """Anthropic provider for production LLM inference via Claude models."""

    def __init__(self, credentials: LLMCredentials):
        super().__init__(credentials)
        self._chat_model: ChatAnthropic | None = None

    async def initialize(self) -> None:
        if self._initialized:
            return

        creds = self._credentials
        if not creds.api_key:
            raise ValueError("Anthropic API key is required")

        logger.info(f"Initializing Anthropic provider with model {creds.model}")

        kwargs: dict[str, Any] = {
            "api_key": creds.api_key,
            "model": creds.model,
            "timeout": (
                creds.timeout if creds.timeout is not None else agent_settings.AGENT_LLM_TIMEOUT
            ),
            # Required by Anthropic's API, so there is no "send none" here.
            # Left unset it would be LangChain's own 4096, which is what a
            # reasoning model spends on thinking before it answers -- see
            # ANTHROPIC_MAX_OUTPUT_TOKENS and adapt_to_error below.
            # Always on. Without it the client asks for the whole answer in
            # one piece and there are no token events to forward, so a model
            # that reasons before answering leaves the screen empty for as
            # long as it thinks -- indistinguishable from a hang.
            "streaming": True,
            "max_tokens": (
                creds.max_tokens
                or agent_settings.AGENT_LLM_MAX_TOKENS
                or agent_settings.ANTHROPIC_MAX_OUTPUT_TOKENS
            ),
        }
        if creds.base_url:
            kwargs["base_url"] = creds.base_url

        self._chat_model = ChatAnthropic(**kwargs)
        self._initialized = True
        logger.info("Anthropic provider initialized")

    #: "max_tokens: 200000 > 64000, which is the maximum allowed number of
    #: output tokens for <model>" -- the refusal names the number to use.
    _MAX_TOKENS_REFUSAL = re.compile(r"max_tokens:\s*(\d+)\s*>\s*(\d+)")

    def adapt_to_error(self, error: Exception) -> bool:
        """Lower this client's output ceiling to whatever the model allows,
        when that is what the request was refused for.

        Asking for more than a model permits is answered with the number it
        does permit, which makes the API itself the source of truth for a
        figure that otherwise has to live in a table and go stale every time
        a model ships. So the ask starts deliberately high and comes down
        once, on the one request that finds the ceiling; the provider
        instance is cached per credential, so every later turn on that model
        already knows.

        Returns whether anything changed -- i.e. whether retrying is worth
        it. Anything that is not this refusal is left alone.
        """
        match = self._MAX_TOKENS_REFUSAL.search(str(error))
        if match is None or self._chat_model is None:
            return False
        allowed = int(match.group(2))
        current = self._chat_model.max_tokens
        if current is not None and current <= allowed:
            return False  # not what we were refused for
        logger.info(
            "Lowering max_tokens for %s from %s to the model's own maximum %s",
            self._credentials.model, current, allowed,
        )
        self._chat_model.max_tokens = allowed
        return True

    async def shutdown(self) -> None:
        if not self._initialized:
            return
        logger.info("Shutting down Anthropic provider")
        self._chat_model = None
        self._initialized = False

    def get_chat_model(self) -> BaseChatModel:
        if not self._initialized or self._chat_model is None:
            raise RuntimeError("Anthropic provider not initialized")
        return self._chat_model

    async def health_check(self) -> dict[str, Any]:
        try:
            start = time.time()
            model = self.get_chat_model()
            await model.ainvoke([{"role": "user", "content": "ping"}])
            latency = (time.time() - start) * 1000
            return {
                "status": "healthy",
                "provider": self.provider_name,
                "model": self._credentials.model,
                "latency_ms": round(latency, 2),
            }
        except Exception as e:
            logger.error(f"Anthropic health check failed: {e}")
            return {
                "status": "unhealthy",
                "provider": self.provider_name,
                "error": str(e),
            }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def generate(self, messages: list[BaseMessage], **kwargs: Any) -> BaseMessage:
        return await self.get_chat_model().ainvoke(messages, **kwargs)

    async def stream(  # NOSONAR
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[str]:
        async for chunk in self.get_chat_model().astream(messages, **kwargs):
            if hasattr(chunk, "content") and chunk.content:
                content = chunk.content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            yield block.get("text", "")
                        elif isinstance(block, str):
                            yield block
                else:
                    yield content

    @property
    def provider_name(self) -> str:
        return "anthropic"
