"""Repository for GeneratedFile model operations."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.generated_file import GeneratedFile
from src.infrastructure.postgres.repositories.base import BasePostgresRepository


class FileRepository(BasePostgresRepository[GeneratedFile]):
    """Repository for managing generated file entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(GeneratedFile, session)

    async def create(
        self,
        session_id: str,
        user_id: UUID,
        filename: str,
        content: str,
        expires_at: datetime,
        content_type: str = "application/xml",
    ) -> GeneratedFile:
        """Store a new generated file."""
        generated_file = GeneratedFile(
            session_id=session_id,
            user_id=user_id,
            filename=filename,
            content=content,
            content_type=content_type,
            expires_at=expires_at,
        )
        self.session.add(generated_file)
        await self.session.flush()
        await self.session.refresh(generated_file)
        return generated_file

    async def get_by_id_and_user(self, file_id: UUID, user_id: UUID) -> GeneratedFile | None:
        """Get a file by ID, verifying ownership and expiry."""
        result = await self.session.execute(
            select(GeneratedFile).where(
                GeneratedFile.id == file_id,
                GeneratedFile.user_id == user_id,
                GeneratedFile.expires_at > datetime.now(UTC),
            )
        )
        return result.scalar_one_or_none()

    async def cleanup_expired(self) -> int:
        """Delete all expired files. Returns the number of deleted rows."""
        result = await self.session.execute(
            delete(GeneratedFile).where(
                GeneratedFile.expires_at <= datetime.now(UTC),
            )
        )
        await self.session.flush()
        return result.rowcount
