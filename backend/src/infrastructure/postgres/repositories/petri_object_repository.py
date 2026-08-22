"""Repository for PetriObject model operations."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.models.petri_object import PetriObject
from src.infrastructure.postgres.repositories.base import BasePostgresRepository


class PetriObjectRepository(BasePostgresRepository[PetriObject]):
    """Repository for the unified built-in + user-custom template catalog."""

    def __init__(self, session: AsyncSession):
        super().__init__(PetriObject, session)

    async def list_visible(
        self, user_id: uuid.UUID | None
    ) -> list[PetriObject]:
        """
        Return objects visible to the caller: all built-ins plus the user's
        own custom objects (empty user_id => built-ins only).
        """
        if user_id is None:
            stmt = select(PetriObject).where(PetriObject.is_builtin.is_(True))
        else:
            stmt = select(PetriObject).where(
                or_(
                    PetriObject.is_builtin.is_(True),
                    PetriObject.user_id == user_id,
                )
            )
        stmt = stmt.order_by(
            PetriObject.is_builtin.desc(),
            func.lower(PetriObject.name).asc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_visible(
        self, object_id: uuid.UUID, user_id: uuid.UUID | None
    ) -> PetriObject | None:
        """Fetch a built-in by id for anyone, or a user-custom only for its owner."""
        stmt = select(PetriObject).where(PetriObject.id == object_id)
        result = await self.session.execute(stmt)
        instance = result.scalar_one_or_none()
        if instance is None:
            return None
        if instance.is_builtin:
            return instance
        if user_id is not None and instance.user_id == user_id:
            return instance
        return None

    async def get_raw(self, object_id: uuid.UUID) -> PetriObject | None:
        """Fetch a row by id without visibility checks (for ownership-aware endpoints)."""
        result = await self.session.execute(
            select(PetriObject).where(PetriObject.id == object_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_and_name(
        self, user_id: uuid.UUID, name: str
    ) -> PetriObject | None:
        stmt = select(PetriObject).where(
            PetriObject.user_id == user_id,
            PetriObject.is_builtin.is_(False),
            func.lower(PetriObject.name) == name.lower(),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_custom(
        self,
        user_id: uuid.UUID,
        name: str,
        template_data: dict[str, Any],
        description: str | None = None,
        preview_svg: str | None = None,
    ) -> PetriObject:
        instance = PetriObject(
            id=uuid.uuid4(),
            user_id=user_id,
            is_builtin=False,
            name=name,
            description=description,
            template_data=template_data,
            preview_svg=preview_svg,
        )
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update_owned(
        self,
        object_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        template_data: dict[str, Any] | None = None,
        preview_svg: str | None = None,
        clear_description: bool = False,
        clear_preview: bool = False,
    ) -> PetriObject | None:
        """
        Update a user-owned object. Returns None if the row is absent, a
        built-in, or owned by another user.
        """
        result = await self.session.execute(
            select(PetriObject).where(PetriObject.id == object_id)
        )
        instance = result.scalar_one_or_none()
        if instance is None or instance.is_builtin or instance.user_id != user_id:
            return None

        if name is not None:
            instance.name = name
        if template_data is not None:
            instance.template_data = template_data
        if description is not None:
            instance.description = description
        elif clear_description:
            instance.description = None
        if preview_svg is not None:
            instance.preview_svg = preview_svg
        elif clear_preview:
            instance.preview_svg = None
        instance.updated_at = datetime.now(UTC)

        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete_owned(
        self, object_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        """Delete a user-owned object; built-ins and others' rows are untouched."""
        result = await self.session.execute(
            delete(PetriObject).where(
                PetriObject.id == object_id,
                PetriObject.user_id == user_id,
                PetriObject.is_builtin.is_(False),
            )
        )
        await self.session.flush()
        return (result.rowcount or 0) > 0
