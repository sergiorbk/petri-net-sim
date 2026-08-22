"""LLMCredentials value object — what's needed to spin up a provider client."""

import hashlib

from pydantic import BaseModel, ConfigDict, Field

from src.core.agent_config import LLMProvider


class LLMCredentials(BaseModel):
    """
    Immutable bundle of everything needed to talk to an LLM provider.

    Built from a user's BYOK profile after decrypting the stored key:
    ``LLMCredentials(provider=..., api_key=..., model=..., base_url=...)``.

    Treated as a value object: equal credentials produce equal cache keys via
    :meth:`fingerprint`, so the per-credentials provider cache de-duplicates
    callers transparently.
    """

    provider: LLMProvider
    api_key: str | None = None
    model: str
    base_url: str | None = None

    # Optional per-profile overrides. None means "fall back to agent_settings".
    max_tokens: int | None = Field(default=None, ge=1)
    timeout: float | None = Field(default=None, ge=1.0)

    model_config = ConfigDict(frozen=True)

    def fingerprint(self) -> str:
        """
        Stable, secret-aware cache key for this set of credentials.

        SHA-256 over (provider, base_url, model, api_key); the hash never
        leaks the raw key into logs, and equal logical credentials yield
        the same fingerprint regardless of object identity.
        """
        material = "|".join(
            [
                str(self.provider.value),
                self.base_url or "",
                self.model,
                self.api_key or "",
                f"{self.max_tokens}",
                f"{self.timeout}",
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()
