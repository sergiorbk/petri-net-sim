"""Pytest configuration and fixtures."""

import sys
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import JSON, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

# Add src to path for imports
src_path = Path(__file__).parent.parent
sys.path.insert(0, str(src_path))

# Load environment variables before any imports
from dotenv import load_dotenv

load_dotenv()

from src.infrastructure.postgres.base import Base
from src.infrastructure.postgres.models.api_key import ApiKey  # noqa: F401
from src.infrastructure.postgres.models.user import User  # noqa: F401
from src.infrastructure.postgres.models.user_llm_credential import (  # noqa: F401
    UserLLMCredential,
)

# Import all models so metadata knows about every table
from src.infrastructure.postgres.models.session import Session as SessionModel  # noqa: F401
from src.infrastructure.postgres.models.net_snapshot import NetSnapshot  # noqa: F401
from src.infrastructure.postgres.models.petri_object import PetriObject  # noqa: F401
from src.infrastructure.postgres.models.user_net import UserNet  # noqa: F401


# -- JSONB -> JSON adaptation for SQLite --
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return compiler.visit_JSON(JSON(), **kw)


# -- Async SQLite engine for testing --

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create a test engine with in-memory SQLite."""
    _engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    @event.listens_for(_engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield _engine

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(engine):
    """Delete all rows from all tables between tests."""
    yield
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Isolate the in-memory rate limiter so per-test request counts don't
    bleed across tests (which would trip the limiter mid-run)."""
    from src.api.shared.rate_limit import reset_rate_limit_state

    reset_rate_limit_state()
    yield
    reset_rate_limit_state()


@pytest_asyncio.fixture
async def session(engine):
    """Create a new async session for each test."""
    async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def session_factory(engine):
    """Session factory for tests that need to create multiple sessions."""
    return async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


# -- Helper fixtures --


@pytest_asyncio.fixture
async def password_user(session: AsyncSession) -> User:
    """Create a user with email+password credentials in the test database."""
    from src.services.auth.auth_service import hash_password

    user = User(
        id=uuid4(),
        email="user@test.local",
        name="Test User",
        password_hash=hash_password("password123"),
        is_active=True,
        metadata_={},
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture
async def regular_user(session: AsyncSession) -> User:
    """Create a user with no password (e.g. OAuth-only) in the test database."""
    user = User(
        id=uuid4(),
        email="oauth@test.local",
        name="OAuth User",
        is_active=True,
        metadata_={},
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture
async def inactive_user(session: AsyncSession) -> User:
    """Create an inactive user."""
    from src.services.auth.auth_service import hash_password

    user = User(
        id=uuid4(),
        email="inactive@test.local",
        name="Inactive",
        password_hash=hash_password("pass12345"),
        is_active=False,
        metadata_={},
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user
