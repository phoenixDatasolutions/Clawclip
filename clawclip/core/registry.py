"""ClawClip Registry — typed registry for adapters, providers, skills, and agents."""

from __future__ import annotations

import logging
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Registry(Generic[T]):
    """A typed registry that holds named instances.

    Used for platforms, providers, skills, agents, etc.

    Example:
        providers: Registry[LLMProvider] = Registry("providers")
        providers.register("claude_api", claude_provider)
        provider = providers.get("claude_api")
    """

    def __init__(self, registry_name: str = "default") -> None:
        self._name = registry_name
        self._items: dict[str, T] = {}

    @property
    def name(self) -> str:
        return self._name

    def register(self, name: str, instance: T) -> None:
        """Register an instance under a name. Overwrites if exists."""
        if name in self._items:
            logger.warning(
                "Registry '%s': overwriting existing '%s'", self._name, name
            )
        self._items[name] = instance
        logger.debug("Registry '%s': registered '%s'", self._name, name)

    def get(self, name: str) -> T | None:
        """Get an instance by name, or None if not found."""
        return self._items.get(name)

    def require(self, name: str) -> T:
        """Get an instance by name, raising KeyError if not found."""
        if name not in self._items:
            available = ", ".join(self._items.keys()) or "(none)"
            raise KeyError(
                f"Registry '{self._name}': '{name}' not found. Available: {available}"
            )
        return self._items[name]

    def list_all(self) -> dict[str, T]:
        """Return all registered items."""
        return dict(self._items)

    def names(self) -> list[str]:
        """Return all registered names."""
        return list(self._items.keys())

    def has(self, name: str) -> bool:
        """Check if a name is registered."""
        return name in self._items

    def remove(self, name: str) -> T | None:
        """Remove and return an instance by name."""
        return self._items.pop(name, None)

    def clear(self) -> None:
        """Remove all registered items."""
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def __iter__(self):
        return iter(self._items.items())

    def __repr__(self) -> str:
        return f"Registry('{self._name}', items={list(self._items.keys())})"
