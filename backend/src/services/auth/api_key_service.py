"""API Key authentication service."""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth_config import auth_settings
from src.core.logger import get_logger
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.api_key_repository import ApiKeyRepository
from src.infrastructure.postgres.repositories.user_llm_credential_repository import (
    UserLLMCredentialRepository,
)
from src.infrastructure.postgres.repositories.user_repository import UserRepository

logger = get_logger()

API_KEY_PREFIX = "sk-"
# token_urlsafe(36) produces exactly 48 base64url chars → total key: "sk-" + 48 = 51 chars
# This matches OpenAI's key format that OpenAI-compatible clients expect
API_KEY_RANDOM_LENGTH = 36


@dataclass(frozen=True)
class AuthenticatedKey:
    """Result of a successful API key authentication."""

    user: User
    key_hash: str
    key_id: UUID
    llm_credential_id: UUID | None = field(default=None)


class ApiKeyService:
    """Service for API key generation, validation, and lifecycle management."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._api_key_repo = ApiKeyRepository(session)
        self._user_repo = UserRepository(session)
        self._cred_repo = UserLLMCredentialRepository(session)

    @staticmethod
    def _generate_raw_key() -> str:
        """Generate a cryptographically secure raw API key."""
        random_part = secrets.token_urlsafe(API_KEY_RANDOM_LENGTH)
        return f"{API_KEY_PREFIX}{random_part}"

    @staticmethod
    def hash_key(raw_key: str) -> str:
        """Compute SHA-256 hash of a raw API key."""
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_prefix(raw_key: str) -> str:
        """Extract a displayable prefix from a raw key (e.g. 'sk-abc1...')."""
        return raw_key[:8]

    async def create_key(
        self,
        user_id: UUID,
        name: str | None = None,
        llm_credential_id: UUID | None = None,
    ) -> tuple[str, UUID]:
        """
        Create a new API key for a user.

        If llm_credential_id is provided, the key will be bound to that credential.
        All requests authenticated with this key will use that credential automatically.

        Returns:
            Tuple of (raw_key, key_id). The raw_key is shown once and never stored.

        Raises:
            ValueError: if llm_credential_id is provided but not found or not owned by user.
        """
        if llm_credential_id is not None:
            cred = await self._cred_repo.get_active(llm_credential_id, user_id)
            if cred is None:
                raise ValueError(
                    f"LLM credential {llm_credential_id} not found or not owned by this user"
                )

        raw_key = self._generate_raw_key()
        key_hash = self.hash_key(raw_key)
        key_prefix = self._extract_prefix(raw_key)

        api_key = await self._api_key_repo.create(
            user_id=user_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            llm_credential_id=llm_credential_id,
        )
        await self._session.commit()

        logger.info(f"API key created for user {user_id}: {key_prefix}...")
        return raw_key, api_key.id

    async def authenticate(self, raw_key: str) -> AuthenticatedKey | None:
        """
        Authenticate a request using a raw API key.

        Returns:
            AuthenticatedKey with user and key metadata, or None if invalid.
        """
        key_hash = self.hash_key(raw_key)
        api_key = await self._api_key_repo.get_by_hash(key_hash)

        if not api_key:
            return None

        user = await self._user_repo.get_by_id(api_key.user_id)
        if not user or not user.is_active:
            return None

        # last_used_at is informational only. Throttle the write: the Python
        # check skips the UPDATE in the common case (already-fresh timestamp),
        # and the DB-level WHERE clause in update_last_used makes the skip
        # atomic (concurrent requests that race past the Python check still
        # produce at most one effective write per throttle window).
        throttle = auth_settings.API_KEY_LAST_USED_THROTTLE_SECONDS
        if self._should_record_last_used(api_key.last_used_at):
            await self._api_key_repo.update_last_used(api_key.id, throttle_seconds=throttle)
            await self._session.commit()

        return AuthenticatedKey(
            user=user,
            key_hash=key_hash,
            key_id=api_key.id,
            llm_credential_id=api_key.llm_credential_id,
        )

    @staticmethod
    def _should_record_last_used(last_used_at: datetime | None) -> bool:
        """Decide whether to persist a fresh last_used_at, applying the throttle."""
        if last_used_at is None:
            return True

        threshold = auth_settings.API_KEY_LAST_USED_THROTTLE_SECONDS
        if threshold <= 0:
            return True

        # Stored timestamps are timezone-aware (DateTime(timezone=True)); guard
        # against naive values that may come from legacy rows / SQLite tests.
        if last_used_at.tzinfo is None:
            last_used_at = last_used_at.replace(tzinfo=UTC)

        return datetime.now(UTC) - last_used_at >= timedelta(seconds=threshold)

    async def list_keys(self, user_id: UUID) -> list[dict]:
        """List all API keys for a user (metadata only, no hashes)."""
        keys = await self._api_key_repo.list_by_user(user_id)
        return [
            {
                "id": key.id,
                "name": key.name,
                "prefix": key.key_prefix,
                "is_active": key.is_active,
                "last_used_at": key.last_used_at,
                "created_at": key.created_at,
                "llm_credential_id": key.llm_credential_id,
                "llm_credential_name": (
                    key.llm_credential.name if key.llm_credential else None
                ),
            }
            for key in keys
        ]

    async def revoke_key(self, key_id: UUID, user_id: UUID) -> bool:
        """Revoke an API key. Returns False if not found or not owned."""
        result = await self._api_key_repo.deactivate(key_id, user_id)
        if result:
            await self._session.commit()
            logger.info(f"API key {key_id} revoked by user {user_id}")
        return result
