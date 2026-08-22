"""Per-credentials LLM provider factory with TTL-based instance cache.

Replaces the previous singleton-per-process model. Each set of credentials
gets its own provider client instance, cached by credential fingerprint so
repeated requests from the same user reuse the same client (which is what
keeps Anthropic prompt caches warm across HTTP calls).

The factory itself is still process-global; what's per-credentials is the
provider instance it hands out.
"""

import asyncio
import time
from dataclasses import dataclass

from src.core.agent_config import LLMProvider, agent_settings
from src.core.logger import get_logger
from src.services.llm.credentials import LLMCredentials
from src.services.llm.providers.anthropic_provider import AnthropicProvider
from src.services.llm.providers.base import BaseLLMProvider
from src.services.llm.providers.ollama_provider import OllamaProvider
from src.services.llm.providers.openai_provider import OpenAIProvider

logger = get_logger()


_PROVIDER_CLASSES: dict[LLMProvider, type[BaseLLMProvider]] = {
    LLMProvider.OPENAI: OpenAIProvider,
    LLMProvider.ANTHROPIC: AnthropicProvider,
    LLMProvider.OLLAMA: OllamaProvider,
}


@dataclass
class _CacheEntry:
    provider: BaseLLMProvider
    expires_at: float


class LLMFactory:
    """
    Factory that mints and caches per-credentials LLM provider instances.

    Cache key is :meth:`LLMCredentials.fingerprint` so logically equal
    credentials always map to the same client. Entries expire after
    ``LLM_PROVIDER_CACHE_TTL_SECONDS``.

    Cache misses are single-flighted: the factory holds an asyncio lock for
    the duration of provider construction so two concurrent requests with
    fresh credentials don't both pay the initialization cost.
    """

    def __init__(self) -> None:
        self._cache: dict[str, _CacheEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    @staticmethod
    def _build_provider(credentials: LLMCredentials) -> BaseLLMProvider:
        provider_cls = _PROVIDER_CLASSES.get(credentials.provider)
        if provider_cls is None:
            raise ValueError(f"Unsupported LLM provider: {credentials.provider!r}")
        return provider_cls(credentials)

    async def for_credentials(self, credentials: LLMCredentials) -> BaseLLMProvider:
        """
        Return an initialized provider for the given credentials.

        Reuses cached instances when present and unexpired. Concurrent first
        access for the same credentials is single-flighted via a per-key lock.
        """
        key = credentials.fingerprint()
        now = time.monotonic()

        cached = self._cache.get(key)
        if cached is not None and cached.expires_at > now:
            return cached.provider

        # Acquire per-key lock for single-flight construction
        async with self._global_lock:
            lock = self._locks.setdefault(key, asyncio.Lock())

        async with lock:
            cached = self._cache.get(key)
            if cached is not None and cached.expires_at > time.monotonic():
                return cached.provider

            provider = self._build_provider(credentials)
            await provider.initialize()

            ttl = agent_settings.LLM_PROVIDER_CACHE_TTL_SECONDS
            self._cache[key] = _CacheEntry(
                provider=provider,
                expires_at=time.monotonic() + ttl,
            )
            logger.info(
                "LLM provider cached: provider=%s model=%s key=%s",
                provider.provider_name,
                provider.model_name,
                key[:8],
            )
            return provider

    async def shutdown(self) -> None:
        """Tear down every cached provider; called from app lifespan shutdown."""
        for entry in list(self._cache.values()):
            try:
                await entry.provider.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down provider: {e}")
        self._cache.clear()
        self._locks.clear()

    async def evict(self, credentials: LLMCredentials) -> None:
        """Invalidate the cached client for a given credential set (e.g. after rotation)."""
        key = credentials.fingerprint()
        entry = self._cache.pop(key, None)
        self._locks.pop(key, None)
        if entry is not None:
            try:
                await entry.provider.shutdown()
            except Exception as e:
                logger.error(f"Error evicting provider: {e}")

    @property
    def cache_size(self) -> int:
        return len(self._cache)


# --- Process-global factory ---

_llm_factory: LLMFactory | None = None


def get_llm_factory() -> LLMFactory:
    """Return the process-global factory, constructing it on first call."""
    global _llm_factory
    if _llm_factory is None:
        _llm_factory = LLMFactory()
    return _llm_factory


def reset_llm_factory() -> None:
    """Drop the cached factory. Used by tests to start with a clean cache."""
    global _llm_factory
    _llm_factory = None
