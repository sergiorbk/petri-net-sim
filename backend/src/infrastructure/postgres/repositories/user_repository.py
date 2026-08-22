"""Repository for User model operations."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.base import BasePostgresRepository


class UserRepository(BasePostgresRepository[User]):
    """Repository for managing User entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_id(self, id: UUID) -> User | None:
        """Get user by ID."""
        result = await self.session.execute(
            select(User).where(
                User.id == id,
                User.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Get user by email."""
        result = await self.session.execute(
            select(User).where(
                User.email == email,
                User.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list[User]:
        """Get all active, non-deleted users."""
        result = await self.session.execute(
            select(User)
            .where(User.is_deleted == False)  # noqa: E712
            .order_by(User.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        email: str,
        name: str | None = None,
        password_hash: str | None = None,
        picture: str | None = None,
        metadata: dict | None = None,
    ) -> User:
        """Create a new user."""
        user = User(
            email=email,
            name=name,
            password_hash=password_hash,
            picture=picture,
            metadata_=metadata or {},
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update(
        self,
        user: User,
        name: str | None = None,
        picture: str | None = None,
        metadata: dict | None = None,
    ) -> User:
        """Update user info."""
        if name is not None:
            user.name = name
        if picture is not None:
            user.picture = picture
        if metadata is not None:
            user.metadata_ = metadata

        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def deactivate(self, user_id: UUID) -> bool:
        """Deactivate a user."""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.is_active = False
        await self.session.flush()
        return True

    async def activate(self, user_id: UUID) -> bool:
        """Activate a user."""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.is_active = True
        await self.session.flush()
        return True

    async def soft_delete(self, user_id: UUID) -> bool:
        """Soft delete a user."""
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.is_deleted = True
        user.deleted_at = datetime.now(UTC)
        await self.session.flush()
        return True
