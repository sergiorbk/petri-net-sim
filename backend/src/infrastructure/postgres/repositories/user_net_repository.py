"""Repository for UserNet model operations."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.user_net import UserNet
from src.infrastructure.postgres.repositories.base import BasePostgresRepository

SortBy = Literal["updated_at", "created_at"]
_VISIBILITY_VALUES = {"private", "link_only"}


class UserNetRepository(BasePostgresRepository[UserNet]):
    """Repository for user-owned mutable Petri net saves."""

    def __init__(self, session: AsyncSession):
        super().__init__(UserNet, session)

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        limit: int = 24,
        offset: int = 0,
        sort_by: SortBy = "updated_at",
    ) -> tuple[list[UserNet], bool]:
        """Return a page of nets owned by a user.

        Fetches limit+1 rows to detect has_more without a COUNT query.
        Returns (items, has_more).
        """
        order_col = UserNet.created_at if sort_by == "created_at" else UserNet.updated_at
        result = await self.session.execute(
            select(UserNet)
            .where(UserNet.user_id == user_id)
            .order_by(order_col.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def get_owned(
        self, net_id: uuid.UUID, user_id: uuid.UUID
    ) -> UserNet | None:
        """Fetch a net by id only if it belongs to the given user."""
        result = await self.session.execute(
            select(UserNet).where(
                UserNet.id == net_id,
                UserNet.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_for_user(
        self,
        user_id: uuid.UUID,
        name: str,
        net_data: dict[str, Any],
        origin_snapshot_id: uuid.UUID | None = None,
    ) -> UserNet:
        instance = UserNet(
            id=uuid.uuid4(),
            user_id=user_id,
            name=name,
            net_data=net_data,
            origin_snapshot_id=origin_snapshot_id,
        )
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update_owned(
        self,
        net_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        name: str | None = None,
        net_data: dict[str, Any] | None = None,
    ) -> UserNet | None:
        instance = await self.get_owned(net_id, user_id)
        if instance is None:
            return None

        if name is not None:
            instance.name = name
        if net_data is not None:
            instance.net_data = net_data
        instance.updated_at = datetime.now(UTC)

        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_by_share_token(self, share_token: uuid.UUID) -> UserNet | None:
        """Fetch a net by its public share token (no ownership check)."""
        result = await self.session.execute(
            select(UserNet).where(UserNet.share_token == share_token)
        )
        return result.scalar_one_or_none()

    async def update_visibility(
        self, net_id: uuid.UUID, user_id: uuid.UUID, visibility: str
    ) -> UserNet | None:
        """Set visibility on an owned net. Returns the updated net or None if not found."""
        if visibility not in _VISIBILITY_VALUES:
            raise ValueError(f"Invalid visibility: {visibility!r}")
        instance = await self.get_owned(net_id, user_id)
        if instance is None:
            return None
        instance.visibility = visibility
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete_owned(self, net_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(UserNet).where(
                UserNet.id == net_id,
                UserNet.user_id == user_id,
            )
        )
        await self.session.flush()
        return (result.rowcount or 0) > 0
