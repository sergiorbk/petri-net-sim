"""API Key model for bearer token authentication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.postgres.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from src.infrastructure.postgres.models.user_llm_credential import UserLLMCredential


class ApiKey(Base, TimestampMixin, SoftDeleteMixin):
    """Model representing an API key linked to a user."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    key_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    key_prefix: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    llm_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_llm_credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    llm_credential: Mapped[UserLLMCredential | None] = relationship(
        "UserLLMCredential",
        foreign_keys=[llm_credential_id],
        lazy="selectin",
    )
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("idx_api_keys_key_hash", "key_hash", unique=True),
        Index("idx_api_keys_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, prefix={self.key_prefix}, user_id={self.user_id})>"
