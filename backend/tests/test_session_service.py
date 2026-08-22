"""Tests for SessionService — fingerprinting, net persistence, snapshots."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.session import Session as SessionModel
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories.net_snapshot_repository import NetSnapshotRepository
from src.infrastructure.postgres.repositories.session_repository import SessionRepository
from src.services.chat.session_service import SessionService


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


def _sid() -> str:
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestComputeFingerprint:
    def test_deterministic_with_user_id(self):
        uid = uuid.uuid4()
        fp1 = SessionService.compute_fingerprint("Hello", uid)
        fp2 = SessionService.compute_fingerprint("Hello", uid)
        assert fp1 == fp2

    def test_different_content_different_fingerprint(self):
        uid = uuid.uuid4()
        fp1 = SessionService.compute_fingerprint("Hello", uid)
        fp2 = SessionService.compute_fingerprint("World", uid)
        assert fp1 != fp2

    def test_different_user_different_fingerprint(self):
        fp1 = SessionService.compute_fingerprint("Hello", uuid.uuid4())
        fp2 = SessionService.compute_fingerprint("Hello", uuid.uuid4())
        assert fp1 != fp2

    def test_api_key_hash_overrides_user_id(self):
        uid = uuid.uuid4()
        fp_user = SessionService.compute_fingerprint("msg", uid)
        fp_key = SessionService.compute_fingerprint("msg", uid, api_key_hash="abc123")
        assert fp_user != fp_key

    def test_returns_64_char_hex(self):
        fp = SessionService.compute_fingerprint("test", uuid.uuid4())
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


class TestExtractFirstUserContent:
    def test_finds_first_user_message(self):
        msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Second"},
        ]
        result = SessionService.extract_first_user_content(msgs)
        assert result == "Hello"

    def test_returns_none_when_no_user_message(self):
        msgs = [{"role": "system", "content": "system"}]
        assert SessionService.extract_first_user_content(msgs) is None

    def test_returns_none_for_empty_list(self):
        assert SessionService.extract_first_user_content([]) is None

    def test_skips_empty_content(self):
        msgs = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "Real"},
        ]
        result = SessionService.extract_first_user_content(msgs)
        assert result == "Real"


# ---------------------------------------------------------------------------
# Async service methods
# ---------------------------------------------------------------------------


class TestGetOrCreate:
    @pytest.mark.anyio
    async def test_creates_new_session(self, session: AsyncSession):
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()

        result = await svc.get_or_create(sid, user.id)

        assert result.id == sid

    @pytest.mark.anyio
    async def test_returns_existing_session(self, session: AsyncSession):
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()

        s1 = await svc.get_or_create(sid, user.id)
        s2 = await svc.get_or_create(sid, user.id)

        assert s1.id == s2.id


class TestRestoreNetData:
    @pytest.mark.anyio
    async def test_returns_empty_for_unknown_session(self, session: AsyncSession):
        svc = SessionService(session)
        data = await svc.restore_net_data(_sid())
        assert data == {}

    @pytest.mark.anyio
    async def test_returns_stored_net_data(self, session: AsyncSession):
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()
        await svc.get_or_create(sid, user.id)

        repo = SessionRepository(session)
        net = {"places": [{"id": "p1"}]}
        await repo.update_net_data(sid, net)

        data = await svc.restore_net_data(sid)
        assert data == net


class TestSaveNetData:
    @pytest.mark.anyio
    async def test_persists_and_commits(self, session: AsyncSession):
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()
        await svc.get_or_create(sid, user.id)

        net = {"places": [{"id": "p1", "name": "Buffer"}]}
        await svc.save_net_data(sid, net)

        data = await svc.restore_net_data(sid)
        assert data == net


class TestSaveSnapshotAndNet:
    """save_snapshot_and_net delegates to upsert_agent_snapshot."""

    @pytest.mark.anyio
    async def test_returns_none_for_empty_places(self, session: AsyncSession):
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()
        await svc.get_or_create(sid, user.id)

        result = await svc.save_snapshot_and_net(sid, {"places": []})

        assert result is None

    @pytest.mark.anyio
    async def test_returns_snapshot_id_when_net_has_places(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        fixed_id = uuid.uuid4()

        async def _mock_upsert(self, session_id, net_data, content_hash):
            return fixed_id

        monkeypatch.setattr(NetSnapshotRepository, "upsert_agent_snapshot", _mock_upsert)
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()
        await svc.get_or_create(sid, user.id)

        net = {"places": [{"id": "p1", "name": "P1", "tokens": 0}]}
        result = await svc.save_snapshot_and_net(sid, net)

        assert result is not None
        assert len(result) == 36  # UUID string

    @pytest.mark.anyio
    async def test_deduplicates_same_net(self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
        fixed_id = uuid.uuid4()

        async def _mock_upsert(self, session_id, net_data, content_hash):
            return fixed_id

        monkeypatch.setattr(NetSnapshotRepository, "upsert_agent_snapshot", _mock_upsert)
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()
        await svc.get_or_create(sid, user.id)

        net = {"places": [{"id": "p1", "name": "P1", "tokens": 0}]}
        id1 = await svc.save_snapshot_and_net(sid, net)
        id2 = await svc.save_snapshot_and_net(sid, net)

        assert id1 == id2


class TestSetTitleIfEmpty:
    @pytest.mark.anyio
    async def test_sets_title_when_empty(self, session: AsyncSession):
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()
        await svc.get_or_create(sid, user.id)

        await svc.set_title_if_empty(sid, "My Title")

        repo = SessionRepository(session)
        updated = await repo.get_by_id(sid)
        assert updated.title == "My Title"

    @pytest.mark.anyio
    async def test_does_not_overwrite_existing_title(self, session: AsyncSession):
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()
        sess = await svc.get_or_create(sid, user.id)

        repo = SessionRepository(session)
        await repo.update_title(sid, "Original")
        await svc.set_title_if_empty(sid, "Replacement")

        updated = await repo.get_by_id(sid)
        assert updated.title == "Original"

    @pytest.mark.anyio
    async def test_no_error_for_unknown_session(self, session: AsyncSession):
        svc = SessionService(session)
        await svc.set_title_if_empty(_sid(), "Title")  # should not raise

    @pytest.mark.anyio
    async def test_truncates_long_title(self, session: AsyncSession):
        user = await _make_user(session)
        svc = SessionService(session)
        sid = _sid()
        await svc.get_or_create(sid, user.id)

        long_title = "x" * 300
        await svc.set_title_if_empty(sid, long_title)

        repo = SessionRepository(session)
        updated = await repo.get_by_id(sid)
        assert len(updated.title) == 255
