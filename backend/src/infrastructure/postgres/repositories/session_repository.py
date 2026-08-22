"""Repository for Session model operations."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.session import Session
from src.infrastructure.postgres.repositories.base import BasePostgresRepository

_VISIBILITY_VALUES = {"private", "link_only"}


class SessionRepository(BasePostgresRepository[Session]):
    """Repository for managing chat session entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Session, session)

    async def get_or_create(self, session_id: str, user_id: UUID) -> Session:
        """Get an existing session or create a new one."""
        instance = await self.get_by_id(session_id)
        if instance is not None:
            instance.last_accessed_at = datetime.now(UTC)
            await self.session.flush()
            return instance

        new_session = Session(
            id=session_id,
            user_id=user_id,
            net_data={},
            last_accessed_at=datetime.now(UTC),
        )
        self.session.add(new_session)
        await self.session.flush()
        await self.session.refresh(new_session)
        return new_session

    async def get_by_share_token(self, share_token: UUID) -> Session | None:
        """Fetch a session by its public share token."""
        result = await self.session.execute(
            select(Session).where(Session.share_token == share_token)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: UUID, limit: int = 30, offset: int = 0
    ) -> list[Session]:
        """List sessions for a user, ordered by last access, with pagination."""
        result = await self.session.execute(
            select(Session)
            .where(Session.user_id == user_id)
            .order_by(Session.last_accessed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def delete_by_id(self, session_id: str, user_id: UUID) -> bool:
        """Delete a session belonging to a specific user."""
        result = await self.session.execute(
            delete(Session).where(
                Session.id == session_id,
                Session.user_id == user_id,
            )
        )
        await self.session.flush()
        return (result.rowcount or 0) > 0

    async def update_title(self, session_id: str, title: str) -> None:
        """Update the title of a session."""
        await self.session.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(title=title)
        )
        await self.session.flush()

    async def update_messages(self, session_id: str, messages: list) -> None:
        """Persist the frontend message history for a session."""
        await self.session.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(messages=messages)
        )
        await self.session.flush()

    async def update_visibility(self, session_id: str, visibility: str) -> None:
        """Set session visibility. Accepted values: private | link_only | public."""
        if visibility not in _VISIBILITY_VALUES:
            raise ValueError(f"Invalid visibility: {visibility!r}")
        await self.session.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(visibility=visibility)
        )
        await self.session.flush()

    async def update_net_data(self, session_id: str, net_data: dict) -> None:
        """Update the Petri net data for a session."""
        await self.session.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(
                net_data=net_data,
                updated_at=datetime.now(UTC),
                last_accessed_at=datetime.now(UTC),
            )
        )
        await self.session.flush()

    async def update_llm_credential(
        self, session_id: str, llm_credential_id: UUID | None
    ) -> None:
        """Bind a session to a BYOK credential profile (or unbind with None)."""
        await self.session.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(llm_credential_id=llm_credential_id)
        )
        await self.session.flush()
