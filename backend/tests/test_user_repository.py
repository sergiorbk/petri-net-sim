"""Tests for UserRepository — CRUD and lifecycle methods."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.user_repository import UserRepository
from src.services.auth.auth_service import hash_password


async def _create_user(db: AsyncSession, email: str | None = None) -> User:
    repo = UserRepository(db)
    return await repo.create(
        email=email or f"u{uuid.uuid4().hex[:8]}@test.local",
        name="Test User",
        password_hash=hash_password("password123"),
    )


class TestGetById:
    @pytest.mark.anyio
    async def test_returns_existing_user(self, session: AsyncSession):
        user = await _create_user(session)
        repo = UserRepository(session)

        found = await repo.get_by_id(user.id)

        assert found is not None
        assert found.id == user.id

    @pytest.mark.anyio
    async def test_returns_none_for_unknown_id(self, session: AsyncSession):
        repo = UserRepository(session)
        assert await repo.get_by_id(uuid.uuid4()) is None

    @pytest.mark.anyio
    async def test_returns_none_for_deleted_user(self, session: AsyncSession):
        user = await _create_user(session)
        repo = UserRepository(session)
        await repo.soft_delete(user.id)

        found = await repo.get_by_id(user.id)

        assert found is None


class TestGetByEmail:
    @pytest.mark.anyio
    async def test_returns_user_by_email(self, session: AsyncSession):
        email = f"find{uuid.uuid4().hex[:6]}@test.local"
        await _create_user(session, email=email)
        repo = UserRepository(session)

        found = await repo.get_by_email(email)

        assert found is not None
        assert found.email == email

    @pytest.mark.anyio
    async def test_returns_none_for_unknown_email(self, session: AsyncSession):
        repo = UserRepository(session)
        assert await repo.get_by_email("nobody@missing.com") is None

    @pytest.mark.anyio
    async def test_returns_none_for_deleted_users_email(self, session: AsyncSession):
        email = f"deleted{uuid.uuid4().hex[:6]}@test.local"
        user = await _create_user(session, email=email)
        repo = UserRepository(session)
        await repo.soft_delete(user.id)

        assert await repo.get_by_email(email) is None


class TestGetAllActive:
    @pytest.mark.anyio
    async def test_returns_active_users(self, session: AsyncSession):
        repo = UserRepository(session)
        u1 = await _create_user(session)
        u2 = await _create_user(session)

        results = await repo.get_all_active()
        ids = [u.id for u in results]

        assert u1.id in ids
        assert u2.id in ids

    @pytest.mark.anyio
    async def test_excludes_deleted_users(self, session: AsyncSession):
        repo = UserRepository(session)
        alive = await _create_user(session)
        dead = await _create_user(session)
        await repo.soft_delete(dead.id)

        results = await repo.get_all_active()
        ids = [u.id for u in results]

        assert alive.id in ids
        assert dead.id not in ids


class TestCreate:
    @pytest.mark.anyio
    async def test_creates_user_with_all_fields(self, session: AsyncSession):
        repo = UserRepository(session)
        user = await repo.create(
            email="full@test.local",
            name="Full Name",
            password_hash=hash_password("secret123"),
            picture="https://example.com/pic.png",
            metadata={"plan": "pro"},
        )

        assert user.id is not None
        assert user.email == "full@test.local"
        assert user.name == "Full Name"
        assert user.picture == "https://example.com/pic.png"
        assert user.metadata_ == {"plan": "pro"}

    @pytest.mark.anyio
    async def test_creates_user_with_defaults(self, session: AsyncSession):
        repo = UserRepository(session)
        user = await repo.create(email="minimal@test.local")

        assert user.id is not None
        assert user.name is None
        assert user.metadata_ == {}


class TestUpdate:
    @pytest.mark.anyio
    async def test_updates_name(self, session: AsyncSession):
        user = await _create_user(session)
        repo = UserRepository(session)

        updated = await repo.update(user, name="New Name")

        assert updated.name == "New Name"

    @pytest.mark.anyio
    async def test_updates_picture(self, session: AsyncSession):
        user = await _create_user(session)
        repo = UserRepository(session)

        updated = await repo.update(user, picture="https://new.com/pic.jpg")

        assert updated.picture == "https://new.com/pic.jpg"

    @pytest.mark.anyio
    async def test_updates_metadata(self, session: AsyncSession):
        user = await _create_user(session)
        repo = UserRepository(session)

        updated = await repo.update(user, metadata={"tier": "free"})

        assert updated.metadata_ == {"tier": "free"}

    @pytest.mark.anyio
    async def test_omitted_fields_unchanged(self, session: AsyncSession):
        user = await _create_user(session)
        original_email = user.email
        repo = UserRepository(session)

        await repo.update(user, name="Changed")

        assert user.email == original_email


class TestDeactivateAndActivate:
    @pytest.mark.anyio
    async def test_deactivate_sets_inactive(self, session: AsyncSession):
        user = await _create_user(session)
        repo = UserRepository(session)

        result = await repo.deactivate(user.id)

        assert result is True
        refreshed = await repo.get_by_id(user.id)
        assert refreshed.is_active is False

    @pytest.mark.anyio
    async def test_deactivate_returns_false_for_unknown(self, session: AsyncSession):
        repo = UserRepository(session)
        assert await repo.deactivate(uuid.uuid4()) is False

    @pytest.mark.anyio
    async def test_activate_sets_active(self, session: AsyncSession):
        user = await _create_user(session)
        repo = UserRepository(session)
        await repo.deactivate(user.id)

        result = await repo.activate(user.id)

        assert result is True
        refreshed = await repo.get_by_id(user.id)
        assert refreshed.is_active is True

    @pytest.mark.anyio
    async def test_activate_returns_false_for_unknown(self, session: AsyncSession):
        repo = UserRepository(session)
        assert await repo.activate(uuid.uuid4()) is False


class TestSoftDelete:
    @pytest.mark.anyio
    async def test_soft_delete_hides_user(self, session: AsyncSession):
        user = await _create_user(session)
        repo = UserRepository(session)

        result = await repo.soft_delete(user.id)

        assert result is True
        assert await repo.get_by_id(user.id) is None

    @pytest.mark.anyio
    async def test_soft_delete_returns_false_for_unknown(self, session: AsyncSession):
        repo = UserRepository(session)
        assert await repo.soft_delete(uuid.uuid4()) is False

    @pytest.mark.anyio
    async def test_soft_delete_sets_deleted_at(self, session: AsyncSession):
        user = await _create_user(session)
        repo = UserRepository(session)
        await repo.soft_delete(user.id)

        # Row still exists in DB even if get_by_id returns None
        from sqlalchemy import select
        from src.infrastructure.postgres.models.user import User as UserModel
        result = await session.execute(select(UserModel).where(UserModel.id == user.id))
        raw = result.scalar_one()
        assert raw.is_deleted is True
        assert raw.deleted_at is not None
