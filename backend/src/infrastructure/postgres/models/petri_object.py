"""Petri object model - unified catalog of built-in and user-custom subnet templates."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base, TimestampMixin


class PetriObject(Base, TimestampMixin):
    """
    A reusable Petri subnet template that can be instantiated onto a canvas.

    Rows with ``is_builtin=True`` have ``user_id=None`` and are seeded from
    the 14 domain patterns (:mod:`src.domain.patterns`). They are read-only
    for every caller.

    Rows with ``is_builtin=False`` have a non-null ``user_id`` and are
    editable only by their owner.

    ``template_data`` reuses the ``PetriNetData`` JSON shape plus an
    ``interface`` block declaring input / output place ids for hookup at
    drop time.
    """

    __tablename__ = "petri_objects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    is_builtin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    preview_svg: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        kind = "builtin" if self.is_builtin else "user"
        return f"<PetriObject(id={str(self.id)[:8]}..., name={self.name!r}, kind={kind})>"
