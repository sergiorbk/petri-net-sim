"""Tests for BasePostgresRepository — generic CRUD methods."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.base import BasePostgresRepository


class UserBaseRepo(BasePostgresRepository[User]):
    """Thin subclass using User model to exercise base CRUD."""

    def __init__(self, session: AsyncSession):
        super().__init__(User, session)


@pytest.fixture
async def repo(session: AsyncSession) -> UserBaseRepo:
    return UserBaseRepo(session)


def _user(**kwargs) -> User:
    defaults = dict(
        id=uuid.uuid4(),
        email=f"u{uuid.uuid4().hex[:6]}@test.local",
        is_active=True,
        metadata_={},
    )
    defaults.update(kwargs)
    return User(**defaults)


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    @pytest.mark.anyio
    async def test_returns_existing_record(self, repo, session):
        user = _user()
        session.add(user)
        await session.flush()
        found = await repo.get_by_id(user.id)
        assert found is not None
        assert found.id == user.id

    @pytest.mark.anyio
    async def test_returns_none_for_missing(self, repo, session):
        found = await repo.get_by_id(uuid.uuid4())
        assert found is None


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------


class TestGetAll:
    @pytest.mark.anyio
    async def test_returns_all_records(self, repo, session):
        for _ in range(3):
            session.add(_user())
        await session.flush()
        all_records = await repo.get_all(limit=10)
        assert len(all_records) >= 3

    @pytest.mark.anyio
    async def test_limit_is_respected(self, repo, session):
        for _ in range(5):
            session.add(_user())
        await session.flush()
        records = await repo.get_all(limit=2)
        assert len(records) <= 2

    @pytest.mark.anyio
    async def test_offset_skips_records(self, repo, session):
        for _ in range(4):
            session.add(_user())
        await session.flush()
        all_records = await repo.get_all(limit=100)
        offset_records = await repo.get_all(limit=100, offset=2)
        assert len(offset_records) == len(all_records) - 2


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.anyio
    async def test_creates_record(self, repo, session):
        uid = uuid.uuid4()
        record = await repo.create(
            id=uid,
            email="new@test.local",
            is_active=True,
            metadata_={},
        )
        assert record.id == uid
        assert record.email == "new@test.local"


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    @pytest.mark.anyio
    async def test_updates_field(self, repo, session):
        user = _user(name="Original")
        session.add(user)
        await session.flush()
        updated = await repo.update(user.id, name="Updated")
        assert updated is not None
        assert updated.name == "Updated"

    @pytest.mark.anyio
    async def test_returns_none_for_missing(self, repo, session):
        result = await repo.update(uuid.uuid4(), name="X")
        assert result is None


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    @pytest.mark.anyio
    async def test_deletes_record(self, repo, session):
        user = _user()
        session.add(user)
        await session.flush()
        result = await repo.delete(user.id)
        assert result is True
        assert await repo.get_by_id(user.id) is None

    @pytest.mark.anyio
    async def test_returns_false_for_missing(self, repo, session):
        result = await repo.delete(uuid.uuid4())
        assert result is False


# ---------------------------------------------------------------------------
# commit / rollback
# ---------------------------------------------------------------------------


class TestCommitRollback:
    @pytest.mark.anyio
    async def test_commit_does_not_raise(self, repo, session):
        await repo.commit()

    @pytest.mark.anyio
    async def test_rollback_does_not_raise(self, repo, session):
        await repo.rollback()
