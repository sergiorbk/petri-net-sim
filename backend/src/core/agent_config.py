"""Agent and LLM configuration settings."""

from enum import Enum
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class MemoryStrategy(str, Enum):
    """Memory management strategies."""

    SLIDING_WINDOW = "sliding_window"
    TOKEN_WINDOW = "token_window"
    SUMMARIZATION = "summarization"


class AgentSettings(BaseSettings):
    """Agent and LLM configuration."""

    # LLM generation defaults. The provider, model, and API key all come from
    # each user's own BYOK credential profile; these only supply fallbacks for a
    # profile that doesn't set its own max_tokens / timeout.
    # None means "impose no ceiling of our own", which is the default: a
    # ceiling is not a budget, nothing is billed for room left unused, and
    # the only thing a small one buys is a turn that runs out of it. 4096
    # was too little for a model that spends output tokens on reasoning
    # before answering -- the whole allowance went on thinking and the
    # reply came back with no text and no tool calls, which read as a hang.
    #
    # OpenAI and Ollama then get no max_tokens at all. Anthropic's API
    # REQUIRES the field, so there it is asked for at
    # ANTHROPIC_MAX_OUTPUT_TOKENS instead of left to LangChain's own 4096
    # default -- see AnthropicProvider.adapt_to_error for what happens when
    # a particular model allows less than that.
    AGENT_LLM_MAX_TOKENS: Optional[int] = Field(default=None, ge=1)
    # What to ask Anthropic for when nothing else says. Above every current
    # Claude model's own maximum on purpose: asking for more than a model
    # allows is answered with the number it does allow, which is a far more
    # reliable way to find that number than a table that goes stale.
    ANTHROPIC_MAX_OUTPUT_TOKENS: int = Field(default=64000, ge=1)
    # A backstop against a connection that has stopped answering, not a
    # budget for thinking. A reasoning model's first call on a real model
    # was measured at 87 seconds before a token appeared, so two minutes
    # was close enough to normal to cut normal runs off.
    AGENT_LLM_TIMEOUT: float = Field(default=600.0, ge=1.0)

    # Default Ollama endpoint — fallback for BYOK Ollama profiles without a base URL.
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434")

    # Prompt caching toggle for BYOK Anthropic profiles.
    ANTHROPIC_PROMPT_CACHING: bool = Field(default=True)

    # Memory Management
    AGENT_MEMORY_STRATEGY: MemoryStrategy = Field(default=MemoryStrategy.SLIDING_WINDOW)
    # Used by the TOKEN_WINDOW strategy, which really counts tokens.
    AGENT_MEMORY_MAX_TOKENS: int = Field(default=4000, ge=100)
    # Used by SLIDING_WINDOW, which keeps the last N MESSAGES. It used to
    # derive N by dividing the token setting above by a hardcoded "assume
    # 100 tokens per message" -- a message limit wearing a token limit's
    # name, and one that drifted further from the truth the longer the
    # messages got. 40 is what that arithmetic produced, kept so the change
    # is a change of honesty rather than of behaviour.
    AGENT_MEMORY_MAX_MESSAGES: int = Field(default=40, ge=1)
    AGENT_MEMORY_SUMMARIZATION_THRESHOLD: int = Field(default=50, ge=5)


    # Per-credentials provider cache TTL (seconds). Provider clients keep
    # Anthropic prompt caches warm across requests; longer TTL = better cache hit
    # rate at the cost of more idle clients in memory.
    LLM_PROVIDER_CACHE_TTL_SECONDS: int = Field(default=3600, ge=60)

    # Encryption for stored API keys
    # CREDENTIALS_MASTER_KEY: 32-byte URL-safe base64 string used by FernetCipher.
    # Required when CREDENTIALS_CIPHER=fernet. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    CREDENTIALS_CIPHER: Literal["fernet", "noop"] = Field(default="fernet")
    CREDENTIALS_MASTER_KEY: Optional[str] = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


agent_settings = AgentSettings()
