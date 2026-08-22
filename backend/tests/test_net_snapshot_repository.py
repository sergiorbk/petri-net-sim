"""Tests for NetSnapshotRepository — get, upsert, create_user, list."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert as sa_insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.net_snapshot import NetSnapshot
from src.infrastructure.postgres.models.session import Session as SessionModel
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.net_snapshot_repository import NetSnapshotRepository


async def _sqlite_upsert(self, session_id: str, net_data: dict, content_hash: str) -> uuid.UUID:
    """SQLite-compatible replacement for upsert_agent_snapshot used in tests."""
    result = await self.session.execute(
        select(NetSnapshot.id).where(
            NetSnapshot.session_id == session_id,
            NetSnapshot.content_hash == content_hash,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    new_id = uuid.uuid4()
    await self.session.execute(
        sa_insert(NetSnapshot).values(
            id=new_id,
            session_id=session_id,
            net_data=net_data,
            content_hash=content_hash,
            source="agent",
            parent_snapshot_id=None,
            label=None,
        )
    )
    return new_id


def _sid() -> str:
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()


def _hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def _make_user_and_session(db: AsyncSession) -> tuple[User, SessionModel]:
    user = User(
        id=uuid.uuid4(),
        email=f"u{uuid.uuid4().hex[:6]}@test.local",
        is_active=True,
        metadata_={},
    )
    db.add(user)
    await db.flush()

    s = SessionModel(
        id=_sid(),
        user_id=user.id,
        net_data={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_accessed_at=datetime.now(UTC),
    )
    db.add(s)
    await db.flush()
    await db.refresh(s)
    return user, s


class TestGetByIdAndSession:
    @pytest.mark.anyio
    async def test_returns_correct_snapshot(self, session: AsyncSession):
        _, sess = await _make_user_and_session(session)
        net_data = {"places": [{"id": "p1", "name": "P1"}]}
        snap = NetSnapshot(
            session_id=sess.id,
            net_data=net_data,
            content_hash=_hash(net_data),
            source="agent",
        )
        session.add(snap)
        await session.flush()
        await session.refresh(snap)

        repo = NetSnapshotRepository(session)
        found = await repo.get_by_id_and_session(snap.id, sess.id)

        assert found is not None
        assert found.id == snap.id

    @pytest.mark.anyio
    async def test_returns_none_wrong_session(self, session: AsyncSession):
        _, sess = await _make_user_and_session(session)
        net_data = {"places": []}
        snap = NetSnapshot(
            session_id=sess.id,
            net_data=net_data,
            content_hash=_hash(net_data),
            source="agent",
        )
        session.add(snap)
        await session.flush()
        await session.refresh(snap)

        repo = NetSnapshotRepository(session)
        found = await repo.get_by_id_and_session(snap.id, _sid())  # wrong session

        assert found is None

    @pytest.mark.anyio
    async def test_returns_none_unknown_id(self, session: AsyncSession):
        _, sess = await _make_user_and_session(session)
        repo = NetSnapshotRepository(session)
        found = await repo.get_by_id_and_session(uuid.uuid4(), sess.id)
        assert found is None


class TestUpsertAgentSnapshot:
    """upsert_agent_snapshot behaviour verified via SQLite-compatible mock."""

    @pytest.mark.anyio
    async def test_inserts_new_snapshot(self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(NetSnapshotRepository, "upsert_agent_snapshot", _sqlite_upsert)
        _, sess = await _make_user_and_session(session)
        net_data = {"places": [{"id": "p1", "name": "Buffer"}]}
        repo = NetSnapshotRepository(session)

        snap_id = await repo.upsert_agent_snapshot(
            session_id=sess.id,
            net_data=net_data,
            content_hash=_hash(net_data),
        )

        assert isinstance(snap_id, uuid.UUID)
        snaps = await repo.list_by_session(sess.id)
        assert len(snaps) == 1
        assert snaps[0].source == "agent"

    @pytest.mark.anyio
    async def test_deduplicates_same_content(self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(NetSnapshotRepository, "upsert_agent_snapshot", _sqlite_upsert)
        _, sess = await _make_user_and_session(session)
        net_data = {"places": [{"id": "p1"}]}
        h = _hash(net_data)
        repo = NetSnapshotRepository(session)

        id1 = await repo.upsert_agent_snapshot(sess.id, net_data, h)
        id2 = await repo.upsert_agent_snapshot(sess.id, net_data, h)

        assert id1 == id2
        assert len(await repo.list_by_session(sess.id)) == 1

    @pytest.mark.anyio
    async def test_different_content_creates_two_rows(self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(NetSnapshotRepository, "upsert_agent_snapshot", _sqlite_upsert)
        _, sess = await _make_user_and_session(session)
        net_a = {"places": [{"id": "p1"}]}
        net_b = {"places": [{"id": "p2"}]}
        repo = NetSnapshotRepository(session)

        id1 = await repo.upsert_agent_snapshot(sess.id, net_a, _hash(net_a))
        id2 = await repo.upsert_agent_snapshot(sess.id, net_b, _hash(net_b))

        assert id1 != id2
        assert len(await repo.list_by_session(sess.id)) == 2


class TestCreateUserSnapshot:
    @pytest.mark.anyio
    async def test_creates_user_snapshot(self, session: AsyncSession):
        _, sess = await _make_user_and_session(session)
        net_data = {"places": [{"id": "p1"}]}
        repo = NetSnapshotRepository(session)

        snap_id = await repo.create_user_snapshot(
            session_id=sess.id,
            net_data=net_data,
            content_hash=_hash(net_data),
            label="Checkpoint v1",
        )

        assert isinstance(snap_id, uuid.UUID)
        snaps = await repo.list_by_session(sess.id)
        assert len(snaps) == 1
        assert snaps[0].source == "user"
        assert snaps[0].label == "Checkpoint v1"

    @pytest.mark.anyio
    async def test_does_not_deduplicate_user_snapshots(self, session: AsyncSession):
        _, sess = await _make_user_and_session(session)
        net_data = {"places": [{"id": "p1"}]}
        h = _hash(net_data)
        repo = NetSnapshotRepository(session)

        id1 = await repo.create_user_snapshot(sess.id, net_data, h)
        id2 = await repo.create_user_snapshot(sess.id, net_data, h)

        assert id1 != id2
        assert len(await repo.list_by_session(sess.id)) == 2

    @pytest.mark.anyio
    async def test_creates_with_parent(self, session: AsyncSession):
        _, sess = await _make_user_and_session(session)
        net_a = {"places": [{"id": "p1"}]}
        repo = NetSnapshotRepository(session)
        parent_id = await repo.create_user_snapshot(sess.id, net_a, _hash(net_a))

        net_b = {"places": [{"id": "p2"}]}
        child_id = await repo.create_user_snapshot(
            sess.id, net_b, _hash(net_b), parent_snapshot_id=parent_id
        )

        snaps = {s.id: s for s in await repo.list_by_session(sess.id)}
        assert snaps[child_id].parent_snapshot_id == parent_id


class TestListBySession:
    @pytest.mark.anyio
    async def test_returns_ordered_by_creation(self, session: AsyncSession):
        _, sess = await _make_user_and_session(session)
        repo = NetSnapshotRepository(session)

        ids = []
        for i in range(3):
            nd = {"i": i}
            snap_id = await repo.create_user_snapshot(sess.id, nd, _hash(nd))
            ids.append(snap_id)

        snaps = await repo.list_by_session(sess.id)
        assert [s.id for s in snaps] == ids

    @pytest.mark.anyio
    async def test_empty_for_unknown_session(self, session: AsyncSession):
        repo = NetSnapshotRepository(session)
        snaps = await repo.list_by_session(_sid())
        assert snaps == []
