"""Tests for MCP in-memory session store."""

from __future__ import annotations

import asyncio
import time

import pytest

from src.mcp.session_store import SessionStore
from src.services.petri.session import PetriNetSession


class TestSessionStore:
    @pytest.mark.anyio
    async def test_get_or_create_new_session(self):
        store = SessionStore()
        session = await store.get_or_create("sess-1")
        assert isinstance(session, PetriNetSession)

    @pytest.mark.anyio
    async def test_get_or_create_returns_same_session(self):
        store = SessionStore()
        s1 = await store.get_or_create("sess-1")
        s2 = await store.get_or_create("sess-1")
        assert s1 is s2

    @pytest.mark.anyio
    async def test_get_existing_session(self):
        store = SessionStore()
        created = await store.get_or_create("sess-1")
        fetched = await store.get("sess-1")
        assert fetched is created

    @pytest.mark.anyio
    async def test_get_nonexistent_returns_none(self):
        store = SessionStore()
        result = await store.get("no-such-session")
        assert result is None

    @pytest.mark.anyio
    async def test_remove_session(self):
        store = SessionStore()
        await store.get_or_create("sess-1")
        assert store.active_count == 1
        await store.remove("sess-1")
        assert store.active_count == 0
        assert await store.get("sess-1") is None

    @pytest.mark.anyio
    async def test_remove_nonexistent_does_not_raise(self):
        store = SessionStore()
        await store.remove("no-such-session")  # should not raise

    @pytest.mark.anyio
    async def test_cleanup_expired(self):
        store = SessionStore(ttl_seconds=0)
        await store.get_or_create("sess-1")
        await store.get_or_create("sess-2")
        # With ttl=0, all sessions are immediately expired
        count = await store.cleanup_expired()
        assert count == 2
        assert store.active_count == 0

    @pytest.mark.anyio
    async def test_cleanup_not_expired(self):
        store = SessionStore(ttl_seconds=3600)
        await store.get_or_create("sess-1")
        count = await store.cleanup_expired()
        assert count == 0
        assert store.active_count == 1

    @pytest.mark.anyio
    async def test_active_count(self):
        store = SessionStore()
        assert store.active_count == 0
        await store.get_or_create("a")
        await store.get_or_create("b")
        assert store.active_count == 2
        await store.remove("a")
        assert store.active_count == 1

    @pytest.mark.anyio
    async def test_concurrent_access_returns_same_session(self):
        store = SessionStore()
        results = await asyncio.gather(
            store.get_or_create("shared"),
            store.get_or_create("shared"),
            store.get_or_create("shared"),
        )
        assert results[0] is results[1] is results[2]