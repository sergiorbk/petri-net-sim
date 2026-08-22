import time
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.database_config import postgres_settings


def get_database_url() -> str:
    """Get the database URL for migrations and other uses."""
    return postgres_settings.DATABASE_URL

# Create async engine
engine = create_async_engine(
    postgres_settings.DATABASE_URL, **postgres_settings.engine_config
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_postgres_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_database_health(session: AsyncSession) -> dict:
    """Check database health for monitoring"""
    try:
        start = time.time()
        await session.execute(text("SELECT 1"))
        latency = (time.time() - start) * 1000

        pool = session.bind.pool

        return {
            "status": "healthy",
            "latency_ms": round(latency, 2),
            "pool_size": pool.size(),
            "pool_checked_in": pool.checkedin(),
            "pool_checked_out": pool.checkedout(),
            "pool_overflow": pool.overflow(),
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
