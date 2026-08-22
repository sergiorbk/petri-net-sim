"""OpenAI / OpenAI-compatible LLM provider."""

import time
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.agent_config import agent_settings
from src.core.logger import get_logger
from src.services.llm.credentials import LLMCredentials
from src.services.llm.providers.base import BaseLLMProvider

logger = get_logger()


class OpenAIProvider(BaseLLMProvider):
    """OpenAI provider for production LLM inference (also LM Studio / Azure-compatible)."""

    def __init__(self, credentials: LLMCredentials):
        super().__init__(credentials)
        self._chat_model: ChatOpenAI | None = None

    async def initialize(self) -> None:
        if self._initialized:
            return

        creds = self._credentials
        if not creds.api_key:
            raise ValueError("OpenAI API key is required")

        logger.info(f"Initializing OpenAI provider with model {creds.model}")

        kwargs: dict[str, Any] = {
            "api_key": creds.api_key,
            "model": creds.model,
            "timeout": (
                creds.timeout if creds.timeout is not None else agent_settings.AGENT_LLM_TIMEOUT
            ),
            # Always on. Without it the client asks for the whole answer in
            # one piece and there are no token events to forward, so a model
            # that reasons before answering leaves the screen empty for as
            # long as it thinks -- indistinguishable from a hang.
            "streaming": True,
        }
        max_tokens = creds.max_tokens or agent_settings.AGENT_LLM_MAX_TOKENS
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if creds.base_url:
            kwargs["base_url"] = creds.base_url

        self._chat_model = ChatOpenAI(**kwargs)
        self._initialized = True
        logger.info("OpenAI provider initialized")

    async def shutdown(self) -> None:
        if not self._initialized:
            return
        logger.info("Shutting down OpenAI provider")
        self._chat_model = None
        self._initialized = False

    def get_chat_model(self) -> BaseChatModel:
        if not self._initialized or self._chat_model is None:
            raise RuntimeError("OpenAI provider not initialized")
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
            logger.error(f"OpenAI health check failed: {e}")
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

    async def stream(
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[str]:
        async for chunk in self.get_chat_model().astream(messages, **kwargs):
            if hasattr(chunk, "content") and chunk.content:
                yield chunk.content

    @property
    def provider_name(self) -> str:
        return "openai"
