"""ORM model for user-owned BYOK LLM credential profiles."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base, TimestampMixin


class UserLLMCredential(Base, TimestampMixin):
    """
    A user-owned LLM credential profile.

    Stores the *encrypted* API key plus the metadata needed to reconstruct an
    LLMCredentials value object (provider, base_url, model). Ollama entries
    may have a null ``encrypted_api_key`` since the local Ollama server does
    not authenticate.

    Soft-deleted rows keep their unique-name slot occupied via the partial
    index in migration 017 (``deleted_at IS NULL``), so a user can recreate a
    profile with the same name as one they previously deleted.
    """

    __tablename__ = "user_llm_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_api_key: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    cipher_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "provider IN ('openai', 'anthropic', 'ollama')",
            name="ck_user_llm_credentials_provider",
        ),
        Index(
            "uq_user_llm_credentials_user_name_active",
            "user_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("idx_user_llm_credentials_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserLLMCredential(id={self.id}, user_id={self.user_id}, "
            f"provider={self.provider}, name={self.name!r})>"
        )
