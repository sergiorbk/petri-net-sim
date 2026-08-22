"""Service for CRUD-ing user-owned BYOK credential profiles."""

from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.agent_config import LLMProvider
from src.core.logger import get_logger
from src.infrastructure.postgres.models.user_llm_credential import UserLLMCredential
from src.infrastructure.postgres.repositories.user_llm_credential_repository import (
    UserLLMCredentialRepository,
)
from src.services.crypto import CredentialsCipher, DecryptionError, get_cipher
from src.services.llm.credentials import LLMCredentials
from src.services.llm.llm_factory import get_llm_factory

logger = get_logger()


class CredentialAlreadyExistsError(Exception):
    """Raised when (user_id, name) collides with an existing active profile."""


class CredentialNotFoundError(Exception):
    """Raised when a credential is missing or owned by another user."""


class CredentialDecryptionError(Exception):
    """Raised when the stored ciphertext cannot be decrypted (key rotation gap, tamper)."""


class CredentialService:
    """
    Encapsulates encrypt-on-write / decrypt-on-read for credential profiles.

    Routers and the resolver should never touch the cipher or repository
    directly — going through this service guarantees that the raw key never
    reaches the DB unencrypted and that previews are always masked.
    """

    PREVIEW_HEAD = 6
    PREVIEW_TAIL = 4

    def __init__(
        self,
        session: AsyncSession,
        cipher: CredentialsCipher | None = None,
    ):
        self._session = session
        self._repo = UserLLMCredentialRepository(session)
        self._cipher = cipher or get_cipher()

    # --- Construction & masking ---

    @classmethod
    def mask(cls, raw_key: str | None) -> str:
        """Return a UI-safe preview that does not reveal the secret."""
        if not raw_key:
            return ""
        if len(raw_key) <= cls.PREVIEW_HEAD + cls.PREVIEW_TAIL:
            return "***"
        return f"{raw_key[: cls.PREVIEW_HEAD]}...{raw_key[-cls.PREVIEW_TAIL :]}"

    def to_credentials(self, row: UserLLMCredential) -> LLMCredentials:
        """Convert a stored profile into a runtime LLMCredentials value object."""
        api_key: str | None = None
        if row.encrypted_api_key is not None:
            try:
                api_key = self._cipher.decrypt(row.encrypted_api_key)
            except DecryptionError as e:
                raise CredentialDecryptionError(
                    f"Stored credential {row.id} cannot be decrypted with the "
                    "current master key. Has CREDENTIALS_MASTER_KEY changed?"
                ) from e

        try:
            provider = LLMProvider(row.provider)
        except ValueError as e:
            raise CredentialDecryptionError(
                f"Stored credential {row.id} has unknown provider {row.provider!r}"
            ) from e

        return LLMCredentials(
            provider=provider,
            api_key=api_key,
            model=row.model,
            base_url=row.base_url,
        )

    def to_response_dict(self, row: UserLLMCredential) -> dict[str, Any]:
        """
        Build the dict consumed by LLMCredentialResponse without leaking the
        raw key. Decrypts solely to compute the masked preview.
        """
        preview = ""
        if row.encrypted_api_key is not None:
            try:
                preview = self.mask(self._cipher.decrypt(row.encrypted_api_key))
            except DecryptionError:
                # Surface as ??? so the UI can prompt for re-entry instead of crashing
                preview = "???"

        return {
            "id": row.id,
            "name": row.name,
            "provider": row.provider,
            "api_key_preview": preview,
            "base_url": row.base_url,
            "model": row.model,
            "created_at": row.created_at,
            "last_validated_at": row.last_validated_at,
        }

    # --- CRUD ---

    async def create(
        self,
        user_id: UUID,
        name: str,
        provider: str,
        model: str,
        api_key: str | None,
        base_url: str | None,
    ) -> UserLLMCredential:
        encrypted = self._cipher.encrypt(api_key) if api_key else None
        try:
            row = await self._repo.create(
                user_id=user_id,
                name=name,
                provider=provider,
                model=model,
                encrypted_api_key=encrypted,
                cipher_version=self._cipher.version,
                base_url=base_url,
            )
            await self._session.commit()
            return row
        except IntegrityError as e:
            await self._session.rollback()
            raise CredentialAlreadyExistsError(
                f"A credential profile named {name!r} already exists for this user."
            ) from e

    async def list_for_user(self, user_id: UUID) -> list[UserLLMCredential]:
        return await self._repo.list_by_user(user_id)

    async def get_for_user(
        self, credential_id: UUID, user_id: UUID
    ) -> UserLLMCredential:
        row = await self._repo.get_active(credential_id, user_id)
        if row is None:
            raise CredentialNotFoundError(str(credential_id))
        return row

    async def update(
        self,
        credential_id: UUID,
        user_id: UUID,
        *,
        name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> UserLLMCredential:
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if model is not None:
            fields["model"] = model
        if base_url is not None:
            fields["base_url"] = base_url
        if api_key is not None:
            fields["encrypted_api_key"] = self._cipher.encrypt(api_key)
            fields["cipher_version"] = self._cipher.version

        if not fields:
            return await self.get_for_user(credential_id, user_id)

        try:
            updated = await self._repo.update_fields(
                credential_id, user_id, **fields
            )
            if updated is None:
                raise CredentialNotFoundError(str(credential_id))
            await self._session.commit()
        except IntegrityError as e:
            await self._session.rollback()
            raise CredentialAlreadyExistsError(
                f"A credential profile named {name!r} already exists for this user."
            ) from e

        # If the key changed, the cached provider client is now stale — evict it.
        if "encrypted_api_key" in fields:
            try:
                creds = self.to_credentials(updated)
                await get_llm_factory().evict(creds)
            except CredentialDecryptionError:
                logger.warning(
                    "Could not decrypt updated credential %s for cache eviction", updated.id
                )
        return updated

    async def delete(self, credential_id: UUID, user_id: UUID) -> None:
        # Capture credentials before delete so we can also evict the cache
        existing = await self._repo.get_active(credential_id, user_id)
        deleted = await self._repo.soft_delete(credential_id, user_id)
        if not deleted:
            raise CredentialNotFoundError(str(credential_id))
        await self._session.commit()

        if existing is not None:
            try:
                creds = self.to_credentials(existing)
                await get_llm_factory().evict(creds)
            except CredentialDecryptionError:
                pass

    # --- Test endpoint ---

    async def test(
        self, credential_id: UUID, user_id: UUID
    ) -> tuple[bool, float | None, str | None, str | None]:
        """
        Verify reachability + auth by sending a tiny "ping" completion.

        Returns (success, latency_ms, model_response_preview, error).
        """
        import time

        row = await self.get_for_user(credential_id, user_id)
        creds = self.to_credentials(row)

        try:
            provider = await get_llm_factory().for_credentials(creds)
            start = time.monotonic()
            response = await provider.generate([HumanMessage(content="ping")])
            latency_ms = (time.monotonic() - start) * 1000

            content = getattr(response, "content", "") or ""
            if isinstance(content, list):
                # Anthropic returns blocks
                preview_parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        preview_parts.append(block.get("text", ""))
                preview = "".join(preview_parts)
            else:
                preview = str(content)

            await self._repo.touch_validated(credential_id)
            await self._session.commit()
            return True, round(latency_ms, 2), preview[:200] or None, None
        except Exception as e:
            logger.warning(f"Credential test failed for {credential_id}: {e}")
            return False, None, None, str(e)
