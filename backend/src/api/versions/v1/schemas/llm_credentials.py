"""Schemas for the BYOK LLM credentials CRUD API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

# Mirror the DB-level CHECK constraint so validation fails before the row hits Postgres.
ProviderType = Literal["openai", "anthropic", "ollama"]


class CreateLLMCredentialRequest(BaseModel):
    """Request body for POST /llm-credentials."""

    name: str = Field(min_length=1, max_length=64, description="User-defined label")
    provider: ProviderType = Field(description="LLM provider")
    api_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="Raw API key (Ollama may omit this).",
    )
    base_url: HttpUrl | None = Field(
        default=None,
        description="Optional override (LM Studio, Azure, self-hosted Ollama, etc.).",
    )
    model: str = Field(
        min_length=1,
        max_length=128,
        description="Model identifier — e.g. gpt-4o, claude-haiku-4-5-20251001, llama3.2",
    )

    @field_validator("api_key")
    @classmethod
    def _strip_api_key(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    def require_key_for_provider(self) -> None:
        """OpenAI and Anthropic always need a key; Ollama is the exception."""
        if self.provider in ("openai", "anthropic") and not self.api_key:
            raise ValueError(f"api_key is required for provider {self.provider!r}")


class UpdateLLMCredentialRequest(BaseModel):
    """Request body for PATCH /llm-credentials/{id}. All fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    api_key: str | None = Field(default=None, min_length=1, max_length=512)
    base_url: HttpUrl | None = Field(default=None)
    model: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("api_key")
    @classmethod
    def _strip_api_key(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class LLMCredentialResponse(BaseModel):
    """Read-side projection — never exposes the raw key."""

    id: UUID
    name: str
    provider: ProviderType
    api_key_preview: str = Field(
        description="Masked preview of the stored key (e.g. 'sk-...abc'). Empty for Ollama."
    )
    base_url: str | None
    model: str
    created_at: datetime
    last_validated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TestLLMCredentialResponse(BaseModel):
    """Response from POST /llm-credentials/{id}/test."""

    success: bool
    latency_ms: float | None = None
    model_response_preview: str | None = None
    error: str | None = None
