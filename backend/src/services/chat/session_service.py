"""Session management service for server-side state persistence."""

import hashlib
import json
import uuid as _uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.infrastructure.postgres.models.session import Session
from src.infrastructure.postgres.repositories.net_snapshot_repository import NetSnapshotRepository
from src.infrastructure.postgres.repositories.session_repository import SessionRepository

logger = get_logger()


class SessionService:
    """Service for managing chat sessions and their Petri net state."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = SessionRepository(session)

    @property
    def session_repository(self) -> SessionRepository:
        """Access the underlying repository (used by the chat service for FK binding)."""
        return self._repo

    @staticmethod
    def compute_fingerprint(
        first_user_content: str,
        user_id: UUID,
        api_key_hash: str | None = None,
    ) -> str:
        """
        Compute a deterministic session fingerprint.

        Uses SHA-256 of (api_key_hash or user_id) + first user message content.
        Same user + same first message = same session.
        """
        identity = api_key_hash if api_key_hash else str(user_id)
        raw = f"{identity}:{first_user_content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def extract_first_user_content(messages: list[dict]) -> str | None:
        """Extract the content of the first user message from a message list."""
        for msg in messages:
            if msg.get("role") == "user" and msg.get("content"):
                return msg["content"]
        return None

    async def get_or_create(self, session_id: str, user_id: UUID) -> Session:
        """Get an existing session or create a new one."""
        return await self._repo.get_or_create(session_id, user_id)

    async def restore_net_data(self, session_id: str) -> dict:
        """Load net_data from a session."""
        instance = await self._repo.get_by_id(session_id)
        if instance is None:
            return {}
        return instance.net_data or {}

    async def save_net_data(self, session_id: str, net_data: dict) -> None:
        """Persist updated net_data to the session."""
        await self._repo.update_net_data(session_id, net_data)
        await self._session.commit()

    async def save_snapshot_and_net(
        self,
        session_id: str,
        net_data: dict,
    ) -> str | None:
        """
        Atomically save a net snapshot and update the session's current net_data.

        Returns the snapshot UUID string so the caller can embed it in the SSE
        stream for the frontend to store alongside the chat message.
        Returns None when net_data is empty (no places — nothing to snapshot).

        The two writes (snapshot upsert + session update) share one DB commit so
        the session and its snapshot are always consistent.
        """
        if not net_data.get("places"):
            await self._repo.update_net_data(session_id, net_data)
            await self._session.commit()
            return None

        content_hash = hashlib.sha256(
            json.dumps(net_data, sort_keys=True, default=str).encode()
        ).hexdigest()

        snapshot_repo = NetSnapshotRepository(self._session)
        snapshot_id: _uuid.UUID = await snapshot_repo.upsert_agent_snapshot(
            session_id=session_id,
            net_data=net_data,
            content_hash=content_hash,
        )

        await self._repo.update_net_data(session_id, net_data)
        await self._session.commit()

        return str(snapshot_id)

    async def set_title_if_empty(self, session_id: str, title: str) -> None:
        """Set session title if it is currently empty."""
        instance = await self._repo.get_by_id(session_id)
        if instance and not instance.title:
            await self._repo.update_title(session_id, title[:255])
            await self._session.commit()
