"""Tests for the MCP server lifespan: periodic session cleanup (D1)."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from src.mcp.server import (
    _cleanup_interval_seconds,
    _periodic_cleanup,
    mcp_lifespan,
)


# ---------------------------------------------------------------------------
# _cleanup_interval_seconds: min(TTL/4, 300s)
# ---------------------------------------------------------------------------


class TestCleanupIntervalSeconds:
    def test_short_ttl_uses_quarter(self):
        assert _cleanup_interval_seconds(60) == 15

    def test_long_ttl_caps_at_300(self):
        # TTL/4 = 900, capped to 300
        assert _cleanup_interval_seconds(3600) == 300

    def test_at_the_cap_boundary(self):
        # TTL/4 == 300 exactly
        assert _cleanup_interval_seconds(1200) == 300

    def test_just_under_the_cap(self):
        assert _cleanup_interval_seconds(1000) == 250


# ---------------------------------------------------------------------------
# _periodic_cleanup: runs cleanup_expired() on the given interval
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal AbstractSessionStore double that counts cleanup_expired() calls."""

    def __init__(self, raise_on_call: bool = False) -> None:
        self.calls = 0
        self._raise = raise_on_call

    async def get_or_create(self, session_id: str):  # pragma: no cover - unused here
        raise NotImplementedError

    async def save(self, session_id: str, session) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    async def remove(self, session_id: str) -> None:  # pragma: no cover - unused here
        raise NotImplementedError

    async def cleanup_expired(self) -> int:
        self.calls += 1
        if self._raise:
            raise RuntimeError("boom")
        return 2


class TestPeriodicCleanup:
    @pytest.mark.anyio
    async def test_calls_cleanup_expired_repeatedly(self):
        store = _FakeStore()
        task = asyncio.create_task(_periodic_cleanup(store, interval_seconds=0.01))
        try:
            await asyncio.sleep(0.05)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        assert store.calls >= 2

    @pytest.mark.anyio
    async def test_survives_cleanup_expired_raising(self):
        """A failing cleanup pass must not kill the background loop."""
        store = _FakeStore(raise_on_call=True)
        task = asyncio.create_task(_periodic_cleanup(store, interval_seconds=0.01))
        try:
            await asyncio.sleep(0.05)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        assert store.calls >= 2  # still looping despite the exception

    @pytest.mark.anyio
    async def test_stops_cleanly_on_cancel(self):
        store = _FakeStore()
        task = asyncio.create_task(_periodic_cleanup(store, interval_seconds=10))
        await asyncio.sleep(0)  # let it start and hit the first sleep
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# mcp_lifespan: starts the periodic task, cancels it on shutdown
# ---------------------------------------------------------------------------


class TestMcpLifespanCleanupTask:
    @pytest.mark.anyio
    async def test_lifespan_starts_and_cancels_cleanup_task(self, monkeypatch):
        from src.core.config import settings

        monkeypatch.setattr(settings, "MCP_SESSION_TTL_SECONDS", 60)

        async with mcp_lifespan(server=None) as ctx:
            # The context is usable and the store is the expected type.
            assert ctx.session_store is not None
            # Find the cleanup task among the running tasks.
            tasks = [t for t in asyncio.all_tasks() if t.get_coro().__name__ == "_periodic_cleanup"]
            assert len(tasks) == 1
            cleanup_task = tasks[0]
            assert not cleanup_task.done()

        # After the lifespan exits, the cleanup task must be stopped.
        assert cleanup_task.done()
        assert cleanup_task.cancelled()
