"""Tests for PetriObjectRepository — CRUD and visibility methods."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.petri_object import PetriObject
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.petri_object_repository import (
    PetriObjectRepository,
)


async def _make_user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"u{uuid.uuid4().hex[:6]}@test.local",
        is_active=True,
        metadata_={},
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _make_builtin(db: AsyncSession, name: str = "Builtin") -> PetriObject:
    obj = PetriObject(
        id=uuid.uuid4(),
        user_id=None,
        is_builtin=True,
        name=name,
        template_data={"places": []},
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


@pytest.fixture
async def user(session: AsyncSession) -> User:
    return await _make_user(session)


@pytest.fixture
async def repo(session: AsyncSession) -> PetriObjectRepository:
    return PetriObjectRepository(session)


# ---------------------------------------------------------------------------
# list_visible
# ---------------------------------------------------------------------------


class TestListVisible:
    @pytest.mark.anyio
    async def test_no_user_returns_only_builtins(self, repo, session):
        builtin = await _make_builtin(session, "B1")
        user = await _make_user(session)
        await repo.create_custom(user.id, "Custom", {})
        results = await repo.list_visible(None)
        ids = [r.id for r in results]
        assert builtin.id in ids
        assert all(r.is_builtin for r in results)

    @pytest.mark.anyio
    async def test_user_sees_builtins_and_own_customs(self, repo, user, session):
        builtin = await _make_builtin(session, "B2")
        custom = await repo.create_custom(user.id, "MyCustom", {})
        results = await repo.list_visible(user.id)
        ids = [r.id for r in results]
        assert builtin.id in ids
        assert custom.id in ids

    @pytest.mark.anyio
    async def test_user_does_not_see_other_users_customs(self, repo, user, session):
        other = await _make_user(session)
        other_custom = await repo.create_custom(other.id, "OtherCustom", {})
        results = await repo.list_visible(user.id)
        ids = [r.id for r in results]
        assert other_custom.id not in ids

    @pytest.mark.anyio
    async def test_sorted_builtins_first(self, repo, user, session):
        await _make_builtin(session, "ZBuiltin")
        await repo.create_custom(user.id, "ACustom", {})
        results = await repo.list_visible(user.id)
        # builtins should come before custom (is_builtin DESC)
        builtin_indices = [i for i, r in enumerate(results) if r.is_builtin]
        custom_indices = [i for i, r in enumerate(results) if not r.is_builtin]
        if builtin_indices and custom_indices:
            assert max(builtin_indices) < min(custom_indices)


# ---------------------------------------------------------------------------
# get_visible
# ---------------------------------------------------------------------------


class TestGetVisible:
    @pytest.mark.anyio
    async def test_builtin_visible_to_anyone(self, repo, session):
        builtin = await _make_builtin(session)
        found = await repo.get_visible(builtin.id, None)
        assert found is not None
        assert found.id == builtin.id

    @pytest.mark.anyio
    async def test_builtin_visible_to_user(self, repo, user, session):
        builtin = await _make_builtin(session)
        found = await repo.get_visible(builtin.id, user.id)
        assert found is not None

    @pytest.mark.anyio
    async def test_custom_visible_to_owner(self, repo, user, session):
        custom = await repo.create_custom(user.id, "Mine", {})
        found = await repo.get_visible(custom.id, user.id)
        assert found is not None
        assert found.id == custom.id

    @pytest.mark.anyio
    async def test_custom_not_visible_to_other_user(self, repo, user, session):
        custom = await repo.create_custom(user.id, "Mine", {})
        other = await _make_user(session)
        found = await repo.get_visible(custom.id, other.id)
        assert found is None

    @pytest.mark.anyio
    async def test_custom_not_visible_without_user(self, repo, user, session):
        custom = await repo.create_custom(user.id, "Mine", {})
        found = await repo.get_visible(custom.id, None)
        assert found is None

    @pytest.mark.anyio
    async def test_returns_none_for_unknown_id(self, repo, session):
        found = await repo.get_visible(uuid.uuid4(), None)
        assert found is None


# ---------------------------------------------------------------------------
# get_raw
# ---------------------------------------------------------------------------


class TestGetRaw:
    @pytest.mark.anyio
    async def test_fetches_by_id(self, repo, user, session):
        custom = await repo.create_custom(user.id, "Raw", {})
        found = await repo.get_raw(custom.id)
        assert found is not None
        assert found.id == custom.id

    @pytest.mark.anyio
    async def test_returns_none_for_missing(self, repo, session):
        found = await repo.get_raw(uuid.uuid4())
        assert found is None


# ---------------------------------------------------------------------------
# get_by_user_and_name
# ---------------------------------------------------------------------------


class TestGetByUserAndName:
    @pytest.mark.anyio
    async def test_finds_by_name(self, repo, user, session):
        await repo.create_custom(user.id, "Unique", {})
        found = await repo.get_by_user_and_name(user.id, "Unique")
        assert found is not None
        assert found.name == "Unique"

    @pytest.mark.anyio
    async def test_case_insensitive_lookup(self, repo, user, session):
        await repo.create_custom(user.id, "CaseName", {})
        found = await repo.get_by_user_and_name(user.id, "casename")
        assert found is not None

    @pytest.mark.anyio
    async def test_returns_none_for_wrong_user(self, repo, user, session):
        other = await _make_user(session)
        await repo.create_custom(other.id, "Shared", {})
        found = await repo.get_by_user_and_name(user.id, "Shared")
        assert found is None

    @pytest.mark.anyio
    async def test_returns_none_for_missing_name(self, repo, user, session):
        found = await repo.get_by_user_and_name(user.id, "NoSuch")
        assert found is None


# ---------------------------------------------------------------------------
# create_custom
# ---------------------------------------------------------------------------


class TestCreateCustom:
    @pytest.mark.anyio
    async def test_creates_object(self, repo, user, session):
        obj = await repo.create_custom(user.id, "New", {"places": []})
        assert isinstance(obj.id, uuid.UUID)
        assert obj.name == "New"
        assert obj.user_id == user.id
        assert obj.is_builtin is False

    @pytest.mark.anyio
    async def test_creates_with_description_and_svg(self, repo, user, session):
        obj = await repo.create_custom(
            user.id, "Full", {}, description="desc", preview_svg="<svg/>"
        )
        assert obj.description == "desc"
        assert obj.preview_svg == "<svg/>"


# ---------------------------------------------------------------------------
# update_owned
# ---------------------------------------------------------------------------


class TestUpdateOwned:
    @pytest.mark.anyio
    async def test_updates_name(self, repo, user, session):
        obj = await repo.create_custom(user.id, "Old", {})
        updated = await repo.update_owned(obj.id, user.id, name="New")
        assert updated is not None
        assert updated.name == "New"

    @pytest.mark.anyio
    async def test_updates_template_data(self, repo, user, session):
        obj = await repo.create_custom(user.id, "T", {})
        new_data = {"places": [{"id": "p1"}]}
        updated = await repo.update_owned(obj.id, user.id, template_data=new_data)
        assert updated is not None
        assert updated.template_data == new_data

    @pytest.mark.anyio
    async def test_clear_description(self, repo, user, session):
        obj = await repo.create_custom(user.id, "T", {}, description="old")
        updated = await repo.update_owned(obj.id, user.id, clear_description=True)
        assert updated is not None
        assert updated.description is None

    @pytest.mark.anyio
    async def test_clear_preview(self, repo, user, session):
        obj = await repo.create_custom(user.id, "T", {}, preview_svg="<svg/>")
        updated = await repo.update_owned(obj.id, user.id, clear_preview=True)
        assert updated is not None
        assert updated.preview_svg is None

    @pytest.mark.anyio
    async def test_returns_none_for_wrong_user(self, repo, user, session):
        obj = await repo.create_custom(user.id, "T", {})
        other = await _make_user(session)
        result = await repo.update_owned(obj.id, other.id, name="Hack")
        assert result is None

    @pytest.mark.anyio
    async def test_returns_none_for_builtin(self, repo, user, session):
        builtin = await _make_builtin(session)
        result = await repo.update_owned(builtin.id, user.id, name="Hack")
        assert result is None

    @pytest.mark.anyio
    async def test_returns_none_for_unknown(self, repo, user, session):
        result = await repo.update_owned(uuid.uuid4(), user.id, name="X")
        assert result is None


# ---------------------------------------------------------------------------
# delete_owned
# ---------------------------------------------------------------------------


class TestDeleteOwned:
    @pytest.mark.anyio
    async def test_deletes_owned(self, repo, user, session):
        obj = await repo.create_custom(user.id, "Del", {})
        deleted = await repo.delete_owned(obj.id, user.id)
        assert deleted is True
        assert await repo.get_raw(obj.id) is None

    @pytest.mark.anyio
    async def test_returns_false_for_wrong_user(self, repo, user, session):
        obj = await repo.create_custom(user.id, "Del", {})
        other = await _make_user(session)
        deleted = await repo.delete_owned(obj.id, other.id)
        assert deleted is False

    @pytest.mark.anyio
    async def test_returns_false_for_builtin(self, repo, user, session):
        builtin = await _make_builtin(session)
        deleted = await repo.delete_owned(builtin.id, user.id)
        assert deleted is False
