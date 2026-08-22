"""Per-credentials provider cache behaviour for LLMFactory."""

import asyncio

import pytest

from src.core.agent_config import LLMProvider
from src.services.llm.credentials import LLMCredentials
from src.services.llm.llm_factory import LLMFactory
from src.services.llm.providers.base import BaseLLMProvider


class _FakeProvider(BaseLLMProvider):
    """Minimal provider stand-in for testing the factory."""

    construct_count: int = 0
    init_count: int = 0
    shutdown_count: int = 0

    def __init__(self, credentials: LLMCredentials):
        super().__init__(credentials)
        type(self).construct_count += 1

    async def initialize(self) -> None:
        if self._initialized:
            return
        type(self).init_count += 1
        self._initialized = True

    async def shutdown(self) -> None:
        type(self).shutdown_count += 1
        self._initialized = False

    def get_chat_model(self):
        return object()

    async def health_check(self) -> dict:
        return {"status": "healthy", "provider": "fake"}

    async def generate(self, messages, **kwargs):  # pragma: no cover
        return None

    async def stream(self, messages, **kwargs):  # pragma: no cover
        if False:
            yield ""

    @property
    def provider_name(self) -> str:
        return "fake"


@pytest.fixture(autouse=True)
def _reset_fake_counts():
    _FakeProvider.construct_count = 0
    _FakeProvider.init_count = 0
    _FakeProvider.shutdown_count = 0
    yield


@pytest.fixture
def factory(monkeypatch) -> LLMFactory:
    """Factory with all real provider classes swapped for the fake."""
    monkeypatch.setattr(
        "src.services.llm.llm_factory._PROVIDER_CLASSES",
        {
            LLMProvider.OPENAI: _FakeProvider,
            LLMProvider.ANTHROPIC: _FakeProvider,
            LLMProvider.OLLAMA: _FakeProvider,
        },
    )
    return LLMFactory()


def _creds(api_key: str = "sk-a", model: str = "gpt-4o") -> LLMCredentials:
    return LLMCredentials(provider=LLMProvider.OPENAI, api_key=api_key, model=model)


async def test_returns_provider_for_credentials(factory: LLMFactory):
    provider = await factory.for_credentials(_creds())
    assert isinstance(provider, _FakeProvider)
    assert provider.credentials.api_key == "sk-a"


async def test_caches_same_credentials(factory: LLMFactory):
    a = await factory.for_credentials(_creds())
    b = await factory.for_credentials(_creds())
    assert a is b
    assert _FakeProvider.construct_count == 1
    assert _FakeProvider.init_count == 1


async def test_different_keys_yield_different_providers(factory: LLMFactory):
    a = await factory.for_credentials(_creds(api_key="sk-a"))
    b = await factory.for_credentials(_creds(api_key="sk-b"))
    assert a is not b
    assert _FakeProvider.construct_count == 2


async def test_different_models_yield_different_providers(factory: LLMFactory):
    a = await factory.for_credentials(_creds(model="gpt-4o"))
    b = await factory.for_credentials(_creds(model="gpt-4o-mini"))
    assert a is not b


async def test_user_isolation(factory: LLMFactory):
    """Two users with different keys must not share a provider client."""
    user_a = await factory.for_credentials(_creds(api_key="sk-user-a"))
    user_b = await factory.for_credentials(_creds(api_key="sk-user-b"))
    assert user_a is not user_b
    assert user_a.credentials.api_key == "sk-user-a"
    assert user_b.credentials.api_key == "sk-user-b"


async def test_concurrent_first_access_is_single_flighted(factory: LLMFactory):
    creds = _creds()
    results = await asyncio.gather(*(factory.for_credentials(creds) for _ in range(10)))
    assert len({id(r) for r in results}) == 1
    assert _FakeProvider.construct_count == 1
    assert _FakeProvider.init_count == 1


async def test_evict_drops_provider(factory: LLMFactory):
    creds = _creds()
    a = await factory.for_credentials(creds)
    await factory.evict(creds)
    assert _FakeProvider.shutdown_count == 1

    b = await factory.for_credentials(creds)
    assert a is not b


async def test_shutdown_clears_cache(factory: LLMFactory):
    await factory.for_credentials(_creds(api_key="sk-1"))
    await factory.for_credentials(_creds(api_key="sk-2"))
    assert factory.cache_size == 2

    await factory.shutdown()
    assert factory.cache_size == 0
    assert _FakeProvider.shutdown_count == 2


async def test_ttl_expiry_rebuilds(factory: LLMFactory, monkeypatch):
    # Force TTL=0 so the next lookup is always a miss
    monkeypatch.setattr(
        "src.services.llm.llm_factory.agent_settings.LLM_PROVIDER_CACHE_TTL_SECONDS",
        0,
    )
    a = await factory.for_credentials(_creds())
    b = await factory.for_credentials(_creds())
    # New entry should have been constructed because previous one expired immediately
    assert _FakeProvider.construct_count == 2
    assert a is not b


async def test_credentials_fingerprint_stable():
    a = LLMCredentials(provider=LLMProvider.OPENAI, api_key="sk-a", model="gpt-4o")
    b = LLMCredentials(provider=LLMProvider.OPENAI, api_key="sk-a", model="gpt-4o")
    assert a.fingerprint() == b.fingerprint()


async def test_credentials_fingerprint_includes_key():
    a = LLMCredentials(provider=LLMProvider.OPENAI, api_key="sk-a", model="gpt-4o")
    b = LLMCredentials(provider=LLMProvider.OPENAI, api_key="sk-b", model="gpt-4o")
    assert a.fingerprint() != b.fingerprint()


async def test_credentials_fingerprint_does_not_leak_key():
    creds = LLMCredentials(provider=LLMProvider.OPENAI, api_key="sk-secret", model="gpt-4o")
    fp = creds.fingerprint()
    assert "sk-secret" not in fp
    assert len(fp) == 64  # SHA-256 hex
