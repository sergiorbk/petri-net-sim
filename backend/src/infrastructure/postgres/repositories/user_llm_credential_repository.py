"""Repository for UserLLMCredential model operations."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.user_llm_credential import UserLLMCredential
from src.infrastructure.postgres.repositories.base import BasePostgresRepository


class UserLLMCredentialRepository(BasePostgresRepository[UserLLMCredential]):
    """Repository for managing user-owned BYOK LLM credential profiles."""

    def __init__(self, session: AsyncSession):
        super().__init__(UserLLMCredential, session)

    async def create(
        self,
        user_id: UUID,
        name: str,
        provider: str,
        model: str,
        encrypted_api_key: bytes | None,
        cipher_version: int,
        base_url: str | None = None,
    ) -> UserLLMCredential:
        """Persist a new credential profile."""
        instance = UserLLMCredential(
            user_id=user_id,
            name=name,
            provider=provider,
            model=model,
            encrypted_api_key=encrypted_api_key,
            cipher_version=cipher_version,
            base_url=base_url,
        )
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_active(
        self, credential_id: UUID, user_id: UUID
    ) -> UserLLMCredential | None:
        """Fetch a non-deleted profile owned by the given user."""
        result = await self.session.execute(
            select(UserLLMCredential).where(
                UserLLMCredential.id == credential_id,
                UserLLMCredential.user_id == user_id,
                UserLLMCredential.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_by_name(
        self, user_id: UUID, name: str
    ) -> UserLLMCredential | None:
        """Fetch a non-deleted profile by its user-scoped name."""
        result = await self.session.execute(
            select(UserLLMCredential).where(
                UserLLMCredential.user_id == user_id,
                UserLLMCredential.name == name,
                UserLLMCredential.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: UUID) -> list[UserLLMCredential]:
        """List all non-deleted credential profiles for a user."""
        result = await self.session.execute(
            select(UserLLMCredential)
            .where(
                UserLLMCredential.user_id == user_id,
                UserLLMCredential.deleted_at.is_(None),
            )
            .order_by(UserLLMCredential.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_fields(
        self,
        credential_id: UUID,
        user_id: UUID,
        **fields,
    ) -> UserLLMCredential | None:
        """
        Update mutable fields on a profile owned by the user.

        Returns the refreshed instance, or None when the profile does not exist
        or has been soft-deleted.
        """
        instance = await self.get_active(credential_id, user_id)
        if instance is None:
            return None

        for key, value in fields.items():
            if hasattr(instance, key):
                setattr(instance, key, value)

        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def soft_delete(self, credential_id: UUID, user_id: UUID) -> bool:
        """Mark a profile as deleted. Returns False if the profile is not owned or already gone."""
        result = await self.session.execute(
            update(UserLLMCredential)
            .where(
                UserLLMCredential.id == credential_id,
                UserLLMCredential.user_id == user_id,
                UserLLMCredential.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC))
        )
        await self.session.flush()
        return (result.rowcount or 0) > 0

    async def touch_validated(self, credential_id: UUID) -> None:
        """Stamp last_validated_at after a successful test call."""
        await self.session.execute(
            update(UserLLMCredential)
            .where(UserLLMCredential.id == credential_id)
            .values(last_validated_at=datetime.now(UTC))
        )
        await self.session.flush()
