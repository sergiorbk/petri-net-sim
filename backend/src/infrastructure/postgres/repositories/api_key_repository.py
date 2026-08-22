"""Repository for API Key model operations."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.api_key import ApiKey
from src.infrastructure.postgres.repositories.base import BasePostgresRepository


class ApiKeyRepository(BasePostgresRepository[ApiKey]):
    """Repository for managing API key entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(ApiKey, session)

    async def create(
        self,
        user_id: UUID,
        key_hash: str,
        key_prefix: str,
        name: str | None = None,
        llm_credential_id: UUID | None = None,
    ) -> ApiKey:
        """Create a new API key record."""
        api_key = ApiKey(
            user_id=user_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            llm_credential_id=llm_credential_id,
        )
        self.session.add(api_key)
        await self.session.flush()
        await self.session.refresh(api_key)
        return api_key

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """Look up an active API key by its hash."""
        result = await self.session.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active == True,  # noqa: E712
                ApiKey.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: UUID) -> list[ApiKey]:
        """List all active API keys for a user."""
        result = await self.session.execute(
            select(ApiKey)
            .where(
                ApiKey.user_id == user_id,
                ApiKey.is_deleted == False,  # noqa: E712
            )
            .order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def deactivate(self, key_id: UUID, user_id: UUID) -> bool:
        """Deactivate an API key. Returns False if not found or not owned."""
        result = await self.session.execute(
            update(ApiKey)
            .where(
                ApiKey.id == key_id,
                ApiKey.user_id == user_id,
                ApiKey.is_deleted == False,  # noqa: E712
            )
            .values(
                is_active=False,
                is_deleted=True,
                deleted_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return result.rowcount > 0

    async def update_last_used(self, key_id: UUID, throttle_seconds: int = 0) -> None:
        """Update last_used_at, skipping the write when the value is fresh.

        When throttle_seconds > 0 the WHERE clause includes the staleness check,
        making the skip atomic at the database level (READ COMMITTED sees the
        already-committed value, so concurrent requests don't double-write).
        """
        now = datetime.now(UTC)
        where_clauses = [ApiKey.id == key_id]
        if throttle_seconds > 0:
            cutoff = now - timedelta(seconds=throttle_seconds)
            where_clauses.append(
                or_(ApiKey.last_used_at.is_(None), ApiKey.last_used_at < cutoff)
            )
        await self.session.execute(
            update(ApiKey).where(*where_clauses).values(last_used_at=now)
        )
        await self.session.flush()
