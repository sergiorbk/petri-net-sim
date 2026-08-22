"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from src.services.llm.credentials import LLMCredentials


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    A provider instance is bound to exactly one set of :class:`LLMCredentials`
    for its lifetime. Per-credential isolation is enforced at construction —
    callers never mutate credentials post-init. The factory caches provider
    instances by credential fingerprint so the same logical credentials reuse
    the same in-memory client (which keeps Anthropic prompt caches warm).
    """

    def __init__(self, credentials: LLMCredentials):
        self._credentials = credentials
        self._initialized = False

    @property
    def credentials(self) -> LLMCredentials:
        return self._credentials

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the LLM provider."""

    def adapt_to_error(self, error: Exception) -> bool:
        """Adjust this provider to a refusal it can do something about, and
        say whether retrying the same request is now worth it.

        Exists so a caller can offer any provider a second chance without
        knowing what any of them can adapt to. The default is that nothing
        can be adapted to, which is the honest answer for a provider that
        has not been taught one.
        """
        return False

    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the LLM provider."""

    @abstractmethod
    def get_chat_model(self) -> BaseChatModel:
        """Get the LangChain chat model instance."""

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Perform health check on the LLM provider.

        Returns:
            dict with status, provider name, and latency
        """

    @abstractmethod
    async def generate(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> BaseMessage:
        """Generate a response from the LLM."""

    @abstractmethod
    async def stream(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a response from the LLM."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name."""

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self._credentials.model

    @property
    def supports_streaming(self) -> bool:
        """Check if the provider supports streaming. All current providers do."""
        return True
