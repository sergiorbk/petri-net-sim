"""User model for authentication."""

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base, SoftDeleteMixin, TimestampMixin


class User(Base, TimestampMixin, SoftDeleteMixin):
    """Model representing an authenticated user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    picture: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Auth
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # OAuth provider info (nullable — password-based users don't have these)
    auth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    auth_provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # User status
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    # Additional metadata
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"
