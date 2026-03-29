"""Base Repository — generic CRUD operations."""

from __future__ import annotations

from typing import Any, Generic, TypeVar, get_args

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusai.storage.models.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic repository with CRUD operations.

    Subclass and set model_class, or pass it to __init__.
    """

    model_class: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs: Any) -> T:
        """Create a new record."""
        instance = self.model_class(**kwargs)
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def get(self, id: str) -> T | None:
        """Get a record by ID."""
        return await self._session.get(self.model_class, id)

    async def get_by(self, **kwargs: Any) -> T | None:
        """Get a record by arbitrary filters."""
        stmt = select(self.model_class).filter_by(**kwargs)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_(self, limit: int = 100, offset: int = 0, **filters: Any) -> list[T]:
        """List records with optional filters."""
        stmt = select(self.model_class)
        if filters:
            stmt = stmt.filter_by(**filters)
        stmt = stmt.offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, id: str, **kwargs: Any) -> T | None:
        """Update a record by ID."""
        instance = await self.get(id)
        if instance is None:
            return None
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self._session.flush()
        return instance

    async def delete(self, id: str) -> bool:
        """Delete a record by ID."""
        instance = await self.get(id)
        if instance is None:
            return False
        await self._session.delete(instance)
        await self._session.flush()
        return True

    async def count(self, **filters: Any) -> int:
        """Count records with optional filters."""
        from sqlalchemy import func
        stmt = select(func.count()).select_from(self.model_class)
        if filters:
            stmt = stmt.filter_by(**filters)
        result = await self._session.execute(stmt)
        return result.scalar_one()
