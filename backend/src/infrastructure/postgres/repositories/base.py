from typing import Generic, List, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class BasePostgresRepository(Generic[ModelType]):
    """Base repository with common CRUD operations"""

    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session

    async def get_by_id(self, id: int) -> ModelType | None:
        """Get single record by ID"""
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def get_all(self, limit: int = 100, offset: int = 0) -> List[ModelType]:
        """Get all records with pagination"""
        result = await self.session.execute(
            select(self.model).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> ModelType:
        """Create new record"""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, id: int, **kwargs) -> ModelType | None:
        """Update existing record"""
        instance = await self.get_by_id(id)
        if not instance:
            return None

        for key, value in kwargs.items():
            setattr(instance, key, value)

        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, id: int) -> bool:
        """Delete record by ID"""
        instance = await self.get_by_id(id)
        if not instance:
            return False

        await self.session.delete(instance)
        await self.session.flush()
        return True

    async def commit(self):
        """Commit transaction"""
        await self.session.commit()

    async def rollback(self):
        """Rollback transaction"""
        await self.session.rollback()
