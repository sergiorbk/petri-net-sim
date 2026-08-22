"""Net snapshot model — immutable versioned copies of a session's Petri net."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class NetSnapshot(Base):
    """
    An immutable, content-addressed snapshot of a Petri net at a point in time.

    Snapshots are append-only: once written they are never modified.
    Deduplication is enforced by the unique index on (session_id, content_hash).

    ``source`` distinguishes how the snapshot was created:
      - ``"agent"``  — produced by the LangGraph agent after a chat turn
      - ``"user"``   — created manually by the user (future: in-browser editor)

    ``parent_snapshot_id`` tracks the snapshot this one was forked from
    (future: branching / "take this version and ask the agent to modify it").

    ``label`` is a short user-assigned name shown in the version history UI
    (future: "v2 — added quality check").
    """

    __tablename__ = "net_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    net_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    # SHA-256 hex digest of the canonical (sort_keys=True) JSON of net_data.
    # Used for content-addressed deduplication: the same net produced twice
    # by the agent yields one row, not two.
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    # "agent" | "user"
    source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="agent",
        server_default="agent",
    )
    # Nullable FK to self — set when this snapshot is a fork of another.
    parent_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("net_snapshots.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    # Short human-readable name; populated by user or set to None by agent.
    label: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<NetSnapshot(id={str(self.id)[:8]}…, session={self.session_id[:8]}…, source={self.source})>"
