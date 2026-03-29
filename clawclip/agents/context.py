"""Shared Context — thread-safe key-value store accessible by all agents in a task tree."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SharedContext:
    """Thread-safe key-value store shared between agents in a task tree.

    Supports hierarchical scoping: child contexts can read from parents
    but writes are local to the current scope.
    """

    def __init__(self, parent: SharedContext | None = None) -> None:
        self._data: dict[str, Any] = {}
        self._parent = parent
        self._lock = asyncio.Lock()
        self._artifacts: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []

    async def get(self, key: str, default: Any = None) -> Any:
        """Get a value, checking parent scopes if not found locally."""
        async with self._lock:
            if key in self._data:
                return self._data[key]
        if self._parent:
            return await self._parent.get(key, default)
        return default

    async def set(self, key: str, value: Any) -> None:
        """Set a value in the local scope."""
        async with self._lock:
            self._data[key] = value
            self._history.append({"action": "set", "key": key})

    async def delete(self, key: str) -> None:
        """Delete a value from the local scope."""
        async with self._lock:
            self._data.pop(key, None)

    async def get_all(self) -> dict[str, Any]:
        """Get all values, merging parent scopes."""
        result = {}
        if self._parent:
            result.update(await self._parent.get_all())
        async with self._lock:
            result.update(self._data)
        return result

    async def add_artifact(self, artifact: dict[str, Any]) -> None:
        """Add an artifact (file, result, etc.) to the context."""
        async with self._lock:
            self._artifacts.append(artifact)

    async def get_artifacts(self) -> list[dict[str, Any]]:
        """Get all artifacts, including from parent scopes."""
        result = []
        if self._parent:
            result.extend(await self._parent.get_artifacts())
        async with self._lock:
            result.extend(self._artifacts)
        return result

    def get_history(self) -> list[dict[str, Any]]:
        """Get the history of operations on this context."""
        return list(self._history)

    def create_child(self) -> SharedContext:
        """Create a child context that inherits from this one."""
        return SharedContext(parent=self)
