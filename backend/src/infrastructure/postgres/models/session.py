"""Session model for server-side state persistence."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class Session(Base):
    """Model representing a chat session tied to a user via fingerprint."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    net_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    # Chat message history — synced from the frontend after each completed turn.
    # Stored as a flat list of {role, content, timestamp, snapshot_id?} objects.
    # Nullable: None means not yet synced (new session or pre-014 row).
    messages: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    # Stable token for share links — generated at session creation, never rotated.
    share_token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    # "private" | "link_only" | "public"
    visibility: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="private",
        server_default="private",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    # Flagged when low-level tools (add_place/add_transition/add_arc) are used.
    # Experts can query sessions with this flag to discover new pattern candidates.
    has_custom_topology: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    # BYOK: which credential profile this session is bound to. Set on the first
    # turn that includes metadata.llm_credential_id; reused on subsequent turns
    # so the user does not need to re-pass it. ON DELETE SET NULL — deleting a
    # profile breaks the binding rather than cascading the session away.
    llm_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_llm_credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<Session(id={self.id[:12]}..., user_id={self.user_id}, visibility={self.visibility})>"
