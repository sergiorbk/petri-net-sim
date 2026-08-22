"""Tests for UserNetRepository — CRUD and query methods."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.models.user_net import UserNet
from src.infrastructure.postgres.repositories.user_net_repository import UserNetRepository


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


@pytest.fixture
async def user(session: AsyncSession) -> User:
    return await _make_user(session)


@pytest.fixture
async def repo(session: AsyncSession) -> UserNetRepository:
    return UserNetRepository(session)


# ---------------------------------------------------------------------------
# create_for_user
# ---------------------------------------------------------------------------


class TestCreateForUser:
    @pytest.mark.anyio
    async def test_creates_net(self, repo, user, session):
        net = await repo.create_for_user(user.id, "My Net", {"places": []})
        assert isinstance(net.id, uuid.UUID)
        assert net.name == "My Net"
        assert net.user_id == user.id

    @pytest.mark.anyio
    async def test_creates_without_origin_snapshot(self, repo, user, session):
        net = await repo.create_for_user(user.id, "Base", {}, origin_snapshot_id=None)
        assert net.origin_snapshot_id is None


# ---------------------------------------------------------------------------
# get_owned
# ---------------------------------------------------------------------------


class TestGetOwned:
    @pytest.mark.anyio
    async def test_returns_owned_net(self, repo, user, session):
        net = await repo.create_for_user(user.id, "N", {})
        found = await repo.get_owned(net.id, user.id)
        assert found is not None
        assert found.id == net.id

    @pytest.mark.anyio
    async def test_returns_none_for_wrong_user(self, repo, user, session):
        net = await repo.create_for_user(user.id, "N", {})
        other = await _make_user(session)
        found = await repo.get_owned(net.id, other.id)
        assert found is None

    @pytest.mark.anyio
    async def test_returns_none_for_unknown_id(self, repo, user, session):
        found = await repo.get_owned(uuid.uuid4(), user.id)
        assert found is None


# ---------------------------------------------------------------------------
# list_by_user
# ---------------------------------------------------------------------------


class TestListByUser:
    @pytest.mark.anyio
    async def test_empty_list_for_new_user(self, repo, user, session):
        items, has_more = await repo.list_by_user(user.id)
        assert items == []
        assert has_more is False

    @pytest.mark.anyio
    async def test_lists_owned_nets(self, repo, user, session):
        await repo.create_for_user(user.id, "A", {})
        await repo.create_for_user(user.id, "B", {})
        items, has_more = await repo.list_by_user(user.id)
        assert len(items) == 2
        assert has_more is False

    @pytest.mark.anyio
    async def test_pagination_has_more(self, repo, user, session):
        for i in range(5):
            await repo.create_for_user(user.id, f"Net{i}", {})
        items, has_more = await repo.list_by_user(user.id, limit=3)
        assert len(items) == 3
        assert has_more is True

    @pytest.mark.anyio
    async def test_sort_by_created_at(self, repo, user, session):
        await repo.create_for_user(user.id, "C1", {})
        await repo.create_for_user(user.id, "C2", {})
        items, _ = await repo.list_by_user(user.id, sort_by="created_at")
        assert len(items) == 2


# ---------------------------------------------------------------------------
# update_owned
# ---------------------------------------------------------------------------


class TestUpdateOwned:
    @pytest.mark.anyio
    async def test_updates_name(self, repo, user, session):
        net = await repo.create_for_user(user.id, "Old", {})
        updated = await repo.update_owned(net.id, user.id, name="New")
        assert updated is not None
        assert updated.name == "New"

    @pytest.mark.anyio
    async def test_updates_net_data(self, repo, user, session):
        net = await repo.create_for_user(user.id, "N", {})
        new_data = {"places": [{"id": "p1"}]}
        updated = await repo.update_owned(net.id, user.id, net_data=new_data)
        assert updated is not None
        assert updated.net_data == new_data

    @pytest.mark.anyio
    async def test_returns_none_for_wrong_user(self, repo, user, session):
        net = await repo.create_for_user(user.id, "N", {})
        other = await _make_user(session)
        result = await repo.update_owned(net.id, other.id, name="Hack")
        assert result is None


# ---------------------------------------------------------------------------
# get_by_share_token
# ---------------------------------------------------------------------------


class TestGetByShareToken:
    @pytest.mark.anyio
    async def test_returns_net_by_token(self, repo, user, session):
        net = await repo.create_for_user(user.id, "Shared", {})
        found = await repo.get_by_share_token(net.share_token)
        assert found is not None
        assert found.id == net.id

    @pytest.mark.anyio
    async def test_returns_none_for_unknown_token(self, repo, user, session):
        found = await repo.get_by_share_token(uuid.uuid4())
        assert found is None


# ---------------------------------------------------------------------------
# update_visibility
# ---------------------------------------------------------------------------


class TestUpdateVisibility:
    @pytest.mark.anyio
    async def test_sets_link_only(self, repo, user, session):
        net = await repo.create_for_user(user.id, "N", {})
        updated = await repo.update_visibility(net.id, user.id, "link_only")
        assert updated is not None
        assert updated.visibility == "link_only"

    @pytest.mark.anyio
    async def test_invalid_visibility_raises(self, repo, user, session):
        net = await repo.create_for_user(user.id, "N", {})
        with pytest.raises(ValueError, match="Invalid visibility"):
            await repo.update_visibility(net.id, user.id, "public")

    @pytest.mark.anyio
    async def test_returns_none_for_wrong_user(self, repo, user, session):
        net = await repo.create_for_user(user.id, "N", {})
        other = await _make_user(session)
        result = await repo.update_visibility(net.id, other.id, "link_only")
        assert result is None


# ---------------------------------------------------------------------------
# delete_owned
# ---------------------------------------------------------------------------


class TestDeleteOwned:
    @pytest.mark.anyio
    async def test_deletes_owned_net(self, repo, user, session):
        net = await repo.create_for_user(user.id, "N", {})
        deleted = await repo.delete_owned(net.id, user.id)
        assert deleted is True
        assert await repo.get_owned(net.id, user.id) is None

    @pytest.mark.anyio
    async def test_returns_false_for_wrong_user(self, repo, user, session):
        net = await repo.create_for_user(user.id, "N", {})
        other = await _make_user(session)
        deleted = await repo.delete_owned(net.id, other.id)
        assert deleted is False
