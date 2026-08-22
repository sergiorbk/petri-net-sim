"""PostgreSQL checkpointer for LangGraph state persistence."""

from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.core.database_config import postgres_settings
from src.core.logger import get_logger

logger = get_logger()


class CheckpointerManager:
    """
    Manager for LangGraph PostgreSQL checkpointer.

    Uses the official langgraph-checkpoint-postgres package
    for state persistence.
    """

    _instance: "CheckpointerManager | None" = None
    _checkpointer: AsyncPostgresSaver | None = None
    _context_manager: Any = None
    _initialized: bool = False

    def __new__(cls) -> "CheckpointerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self) -> None:
        """Initialize the checkpointer with database connection."""
        if self._initialized:
            return

        logger.info("Initializing LangGraph checkpointer...")

        try:
            conn_string = self._get_connection_string()

            self._context_manager = AsyncPostgresSaver.from_conn_string(conn_string)
            self._checkpointer = await self._context_manager.__aenter__()

            await self._checkpointer.setup()

            self._initialized = True
            logger.info("LangGraph checkpointer initialized")

        except Exception as e:
            logger.error(f"Failed to initialize checkpointer: {e}")
            raise

    async def shutdown(self) -> None:
        """Shutdown the checkpointer."""
        if not self._initialized:
            return

        logger.info("Shutting down LangGraph checkpointer...")

        if self._context_manager:
            await self._context_manager.__aexit__(None, None, None)
            self._context_manager = None
            self._checkpointer = None

        self._initialized = False
        logger.info("LangGraph checkpointer shut down")

    def get_checkpointer(self) -> AsyncPostgresSaver:
        """Get the checkpointer instance."""
        if not self._initialized or self._checkpointer is None:
            raise RuntimeError("Checkpointer not initialized")
        return self._checkpointer

    def _get_connection_string(self) -> str:
        """Get PostgreSQL connection string for checkpointer."""
        # Use psycopg format for langgraph-checkpoint-postgres
        return (
            f"postgresql://{postgres_settings.DB_USER}:{postgres_settings.DB_PASSWORD}"
            f"@{postgres_settings.DB_HOST}:{postgres_settings.DB_PORT}"
            f"/{postgres_settings.DB_NAME}"
        )

    @property
    def is_initialized(self) -> bool:
        """Check if the checkpointer is initialized."""
        return self._initialized


# Global checkpointer manager instance
_checkpointer_manager: CheckpointerManager | None = None


def get_checkpointer_manager() -> CheckpointerManager:
    """Get or create the global checkpointer manager instance."""
    global _checkpointer_manager
    if _checkpointer_manager is None:
        _checkpointer_manager = CheckpointerManager()
    return _checkpointer_manager


async def get_checkpointer() -> AsyncPostgresSaver:
    """Get the initialized checkpointer instance."""
    manager = get_checkpointer_manager()
    if not manager.is_initialized:
        await manager.initialize()
    return manager.get_checkpointer()
