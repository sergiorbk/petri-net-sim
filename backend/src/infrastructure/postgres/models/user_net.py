"""User net model - mutable workspace saves of a Petri net owned by a user."""

import uuid

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base, TimestampMixin


class UserNet(Base, TimestampMixin):
    """
    A user-owned Petri net that lives in the simulator workspace.

    Unlike :class:`NetSnapshot`, which is immutable and scoped to a chat
    session, a ``UserNet`` is mutable and belongs to a user directly.  The
    simulator app uses these rows as the persistent backing store for
    Save / Save As operations.

    ``origin_snapshot_id`` optionally records the snapshot the user forked
    this net from (e.g. "take this agent-generated net and keep editing it").
    """

    __tablename__ = "user_nets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    net_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    origin_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("net_snapshots.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    share_token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    visibility: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="private",
        server_default="private",
    )

    def __repr__(self) -> str:
        return f"<UserNet(id={str(self.id)[:8]}..., user={str(self.user_id)[:8]}..., name={self.name!r})>"
