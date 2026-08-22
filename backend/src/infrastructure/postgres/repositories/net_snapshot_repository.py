"""Repository for NetSnapshot model operations."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.net_snapshot import NetSnapshot
from src.infrastructure.postgres.repositories.base import BasePostgresRepository


class NetSnapshotRepository(BasePostgresRepository[NetSnapshot]):
    """Append-only repository for content-addressed net snapshots."""

    def __init__(self, session: AsyncSession):
        super().__init__(NetSnapshot, session)

    async def get_by_id_and_session(
        self,
        snapshot_id: uuid.UUID,
        session_id: str,
    ) -> NetSnapshot | None:
        """
        Fetch a snapshot by its UUID, verifying it belongs to session_id.
        Used by the simulate endpoint to enforce ownership without a separate
        session lookup.
        """
        result = await self.session.execute(
            select(NetSnapshot).where(
                NetSnapshot.id == snapshot_id,
                NetSnapshot.session_id == session_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_agent_snapshot(
        self,
        session_id: str,
        net_data: dict,
        content_hash: str,
    ) -> uuid.UUID:
        """
        Insert a new agent-created snapshot, or return the existing one if the
        content hash already exists for this session (idempotent / deduplicated).

        Returns the UUID of the snapshot row (new or pre-existing).
        """
        new_id = uuid.uuid4()

        stmt = (
            pg_insert(NetSnapshot)
            .values(
                id=new_id,
                session_id=session_id,
                net_data=net_data,
                content_hash=content_hash,
                source="agent",
                parent_snapshot_id=None,
                label=None,
            )
            .on_conflict_do_nothing(
                index_elements=["session_id", "content_hash"],
            )
        )
        await self.session.execute(stmt)

        # Whether we just inserted or the row already existed, select the real ID.
        result = await self.session.execute(
            select(NetSnapshot.id).where(
                NetSnapshot.session_id == session_id,
                NetSnapshot.content_hash == content_hash,
            )
        )
        return result.scalar_one()

    async def create_user_snapshot(
        self,
        session_id: str,
        net_data: dict,
        content_hash: str,
        parent_snapshot_id: uuid.UUID | None = None,
        label: str | None = None,
    ) -> uuid.UUID:
        """
        Create a user-initiated snapshot (manual edit or fork).

        User snapshots are NOT deduplicated — the same content may be saved
        multiple times intentionally (e.g. "restore to this state").
        Returns the new snapshot UUID.
        """
        new_id = uuid.uuid4()
        snapshot = NetSnapshot(
            id=new_id,
            session_id=session_id,
            net_data=net_data,
            content_hash=content_hash,
            source="user",
            parent_snapshot_id=parent_snapshot_id,
            label=label,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return new_id

    async def list_by_session(self, session_id: str) -> list[NetSnapshot]:
        """Return all snapshots for a session ordered by creation time."""
        result = await self.session.execute(
            select(NetSnapshot)
            .where(NetSnapshot.session_id == session_id)
            .order_by(NetSnapshot.created_at.asc())
        )
        return list(result.scalars().all())
