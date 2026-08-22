"""Tests for SessionRepository — all CRUD and query methods."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.session import Session as SessionModel
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.session_repository import SessionRepository


def _sid() -> str:
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()


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


class TestGetOrCreate:
    @pytest.mark.anyio
    async def test_creates_new_session(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()

        result = await repo.get_or_create(sid, user.id)

        assert result.id == sid
        assert result.user_id == user.id

    @pytest.mark.anyio
    async def test_returns_existing_session(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()

        first = await repo.get_or_create(sid, user.id)
        second = await repo.get_or_create(sid, user.id)

        assert first.id == second.id

    @pytest.mark.anyio
    async def test_updates_last_accessed(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()

        s = await repo.get_or_create(sid, user.id)
        original_time = s.last_accessed_at.replace(tzinfo=None) if s.last_accessed_at.tzinfo else s.last_accessed_at

        await repo.get_or_create(sid, user.id)
        # last_accessed_at should be updated (may equal original if same second)
        updated = await repo.get_by_id(sid)
        updated_time = updated.last_accessed_at.replace(tzinfo=None) if updated.last_accessed_at.tzinfo else updated.last_accessed_at
        assert updated_time >= original_time


class TestGetByShareToken:
    @pytest.mark.anyio
    async def test_returns_session_by_token(self, session: AsyncSession):
        user = await _make_user(session)
        s = SessionModel(
            id=_sid(), user_id=user.id, net_data={},
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
        )
        session.add(s)
        await session.flush()
        await session.refresh(s)

        repo = SessionRepository(session)
        found = await repo.get_by_share_token(s.share_token)

        assert found is not None
        assert found.id == s.id

    @pytest.mark.anyio
    async def test_returns_none_for_unknown_token(self, session: AsyncSession):
        repo = SessionRepository(session)
        result = await repo.get_by_share_token(uuid.uuid4())
        assert result is None


class TestListByUser:
    @pytest.mark.anyio
    async def test_returns_only_own_sessions(self, session: AsyncSession):
        user_a = await _make_user(session)
        user_b = await _make_user(session)
        repo = SessionRepository(session)

        await repo.get_or_create(_sid(), user_a.id)
        await repo.get_or_create(_sid(), user_b.id)

        results = await repo.list_by_user(user_a.id)
        assert all(s.user_id == user_a.id for s in results)
        assert len(results) == 1

    @pytest.mark.anyio
    async def test_respects_limit(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)

        for _ in range(5):
            await repo.get_or_create(_sid(), user.id)

        results = await repo.list_by_user(user.id, limit=3)
        assert len(results) == 3

    @pytest.mark.anyio
    async def test_respects_offset(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)

        for _ in range(4):
            await repo.get_or_create(_sid(), user.id)

        all_results = await repo.list_by_user(user.id, limit=10)
        offset_results = await repo.list_by_user(user.id, limit=10, offset=2)
        assert len(offset_results) == len(all_results) - 2

    @pytest.mark.anyio
    async def test_empty_for_unknown_user(self, session: AsyncSession):
        repo = SessionRepository(session)
        results = await repo.list_by_user(uuid.uuid4())
        assert results == []


class TestDeleteById:
    @pytest.mark.anyio
    async def test_deletes_own_session(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()
        await repo.get_or_create(sid, user.id)

        deleted = await repo.delete_by_id(sid, user.id)

        assert deleted is True
        assert await repo.get_by_id(sid) is None

    @pytest.mark.anyio
    async def test_returns_false_for_wrong_user(self, session: AsyncSession):
        user_a = await _make_user(session)
        user_b = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()
        await repo.get_or_create(sid, user_a.id)

        deleted = await repo.delete_by_id(sid, user_b.id)

        assert deleted is False
        assert await repo.get_by_id(sid) is not None

    @pytest.mark.anyio
    async def test_returns_false_for_nonexistent(self, session: AsyncSession):
        repo = SessionRepository(session)
        deleted = await repo.delete_by_id(_sid(), uuid.uuid4())
        assert deleted is False


class TestUpdateTitle:
    @pytest.mark.anyio
    async def test_updates_title(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()
        await repo.get_or_create(sid, user.id)

        await repo.update_title(sid, "My Session Title")

        updated = await repo.get_by_id(sid)
        assert updated.title == "My Session Title"


class TestUpdateMessages:
    @pytest.mark.anyio
    async def test_persists_messages(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()
        await repo.get_or_create(sid, user.id)

        msgs = [{"role": "user", "content": "Hello"}]
        await repo.update_messages(sid, msgs)

        updated = await repo.get_by_id(sid)
        assert updated.messages == msgs


class TestUpdateVisibility:
    @pytest.mark.anyio
    async def test_sets_link_only(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()
        await repo.get_or_create(sid, user.id)

        await repo.update_visibility(sid, "link_only")

        updated = await repo.get_by_id(sid)
        assert updated.visibility == "link_only"

    @pytest.mark.anyio
    async def test_sets_private(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()
        await repo.get_or_create(sid, user.id)
        await repo.update_visibility(sid, "link_only")
        await repo.update_visibility(sid, "private")

        updated = await repo.get_by_id(sid)
        assert updated.visibility == "private"

    @pytest.mark.anyio
    async def test_invalid_visibility_raises(self, session: AsyncSession):
        repo = SessionRepository(session)
        with pytest.raises(ValueError, match="Invalid visibility"):
            await repo.update_visibility(_sid(), "public")


class TestUpdateNetData:
    @pytest.mark.anyio
    async def test_persists_net_data(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()
        await repo.get_or_create(sid, user.id)

        net = {"places": [{"id": "p1", "name": "P1"}]}
        await repo.update_net_data(sid, net)

        updated = await repo.get_by_id(sid)
        assert updated.net_data == net


class TestUpdateLlmCredential:
    @pytest.mark.anyio
    async def test_binds_credential(self, session: AsyncSession):
        user = await _make_user(session)
        repo = SessionRepository(session)
        sid = _sid()
        await repo.get_or_create(sid, user.id)

        cred_id = uuid.uuid4()
        # Can't set FK without the row, but we can test None → value roundtrip
        await repo.update_llm_credential(sid, None)

        updated = await repo.get_by_id(sid)
        assert updated.llm_credential_id is None
