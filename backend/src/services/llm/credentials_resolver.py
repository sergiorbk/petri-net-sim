"""Resolve which LLMCredentials a chat completion should use.

The app is BYOK-only: every chat completion must reference a user-owned
credential profile via ``metadata.llm_credential_id`` (or an API key bound to
one). The resolver decides between two outcomes:

  1. A credential is referenced and owned by the user → use those BYOK creds.
  2. No credential is referenced → raise :class:`ByokRequiredError`; the router
     emits 402 ``byok_required``.

Outcomes are surfaced as exceptions instead of mixed return types so the
router can pattern-match on them and emit the right error envelope.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from src.core.logger import get_logger
from src.infrastructure.postgres.models.user import User
from src.services.llm.credential_service import (
    CredentialDecryptionError,
    CredentialNotFoundError,
    CredentialService,
)
from src.services.llm.credentials import LLMCredentials

logger = get_logger()


@dataclass(frozen=True)
class ResolvedCredentials:
    """Outcome of a successful resolution: the creds to use + provenance."""

    credentials: LLMCredentials
    source: Literal["byok"]
    profile_id: UUID | None
    profile_name: str | None


class ByokRequiredError(Exception):
    """No credential profile selected and BYOK is mandatory."""


class InvalidCredentialError(Exception):
    """The metadata referenced a credential that is missing, owned by another user, or undecryptable."""


class CredentialsResolver:
    """Stateless coordinator that turns request metadata into runtime credentials."""

    def __init__(self, credential_service: CredentialService):
        self._credentials = credential_service

    async def resolve(
        self,
        user: User,
        metadata: dict[str, str] | None,
        api_key_credential_id: UUID | None = None,
    ) -> ResolvedCredentials:
        credential_id = self._extract_credential_id(metadata)

        if credential_id is None and api_key_credential_id is not None:
            credential_id = api_key_credential_id

        if credential_id is not None:
            return await self._resolve_byok(user, credential_id)

        raise ByokRequiredError(
            "This deployment requires per-user LLM credentials. Set "
            "metadata.llm_credential_id on the chat completions request."
        )

    async def _resolve_byok(
        self, user: User, credential_id: UUID
    ) -> ResolvedCredentials:
        try:
            row = await self._credentials.get_for_user(credential_id, user.id)
        except CredentialNotFoundError as e:
            raise InvalidCredentialError(
                f"Credential profile {credential_id} not found for this user"
            ) from e

        try:
            creds = self._credentials.to_credentials(row)
        except CredentialDecryptionError as e:
            raise InvalidCredentialError(str(e)) from e

        return ResolvedCredentials(
            credentials=creds,
            source="byok",
            profile_id=row.id,
            profile_name=row.name,
        )

    @staticmethod
    def _extract_credential_id(metadata: dict[str, str] | None) -> UUID | None:
        if not metadata:
            return None
        raw = metadata.get("llm_credential_id")
        if not raw:
            return None
        try:
            return UUID(raw)
        except (ValueError, TypeError) as e:
            raise InvalidCredentialError(
                f"metadata.llm_credential_id is not a valid UUID: {raw!r}"
            ) from e
