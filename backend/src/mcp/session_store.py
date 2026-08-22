"""Session store abstractions and in-memory implementation for MCP server."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.petri.session import PetriNetSession


class AbstractSessionStore(ABC):
    """Base interface for MCP session stores."""

    @abstractmethod
    async def get_or_create(self, session_id: str) -> "PetriNetSession":
        """Get existing session or create a new one."""

    @abstractmethod
    async def save(self, session_id: str, session: "PetriNetSession") -> None:
        """Persist session state. No-op for in-memory stores."""

    @abstractmethod
    async def remove(self, session_id: str) -> None:
        """Remove a session."""

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove stale sessions. Returns count removed."""


class InMemorySessionStore(AbstractSessionStore):
    """
    Thread-safe in-memory store mapping MCP session IDs to PetriNetSession.

    Each MCP connection gets its own PetriNetSession with a live
    PetriNetBuilder instance. Sessions expire after TTL seconds.
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._sessions: dict[str, tuple[PetriNetSession, float]] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def get_or_create(self, session_id: str) -> "PetriNetSession":
        """Get existing session or create a new one."""
        from src.services.petri.session import PetriNetSession

        async with self._lock:
            if session_id in self._sessions:
                session, _ = self._sessions[session_id]
                self._sessions[session_id] = (session, time.monotonic())
                return session

            session = PetriNetSession()
            self._sessions[session_id] = (session, time.monotonic())
            return session

    async def save(self, session_id: str, session: "PetriNetSession") -> None:
        """No-op: session object is already mutated in-place in the dict."""

    async def get(self, session_id: str) -> "PetriNetSession | None":
        """Get existing session, return None if not found."""
        async with self._lock:
            if session_id in self._sessions:
                session, _ = self._sessions[session_id]
                self._sessions[session_id] = (session, time.monotonic())
                return session
            return None

    async def remove(self, session_id: str) -> None:
        """Remove a session."""
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def cleanup_expired(self) -> int:
        """Remove sessions that have exceeded TTL. Returns count removed."""
        async with self._lock:
            now = time.monotonic()
            expired = [
                sid for sid, (_, ts) in self._sessions.items()
                if now - ts > self._ttl
            ]
            for sid in expired:
                del self._sessions[sid]
            return len(expired)

    @property
    def active_count(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)


# Keep backward-compatible alias
SessionStore = InMemorySessionStore
