"""File service for temporary PNML file storage and download."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.infrastructure.postgres.models.generated_file import GeneratedFile
from src.infrastructure.postgres.repositories.file_repository import FileRepository

logger = get_logger()

DEFAULT_TTL_HOURS = 24


class FileService:
    """Service for storing and retrieving generated PNML files."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = FileRepository(session)

    async def store_pnml(
        self,
        session_id: str,
        user_id: UUID,
        pnml_content: str,
        filename: str = "model.pnml",
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> str:
        """
        Store a PNML file and return its ID for download.

        Returns:
            The file ID (UUID as string) for constructing a download URL.
        """
        expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)

        generated_file = await self._repo.create(
            session_id=session_id,
            user_id=user_id,
            filename=filename,
            content=pnml_content,
            expires_at=expires_at,
        )
        await self._session.commit()

        logger.info(f"Stored PNML file {generated_file.id} (expires {expires_at})")
        return str(generated_file.id)

    async def get_file(self, file_id: UUID, user_id: UUID) -> GeneratedFile | None:
        """Get a file by ID, verifying ownership and that it hasn't expired."""
        return await self._repo.get_by_id_and_user(file_id, user_id)

    async def cleanup_expired(self) -> int:
        """Delete expired files. Returns the count of deleted rows."""
        count = await self._repo.cleanup_expired()
        if count > 0:
            await self._session.commit()
            logger.info(f"Cleaned up {count} expired files")
        return count
