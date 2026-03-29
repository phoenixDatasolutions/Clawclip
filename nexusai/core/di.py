"""NexusAI Dependency Injection — lightweight async DI container."""

from __future__ import annotations

import logging
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Container:
    """Lightweight dependency injection container.

    Stores singleton instances by type name or key. Used to wire
    together the EventBus, registries, config, storage, and managers
    without passing them through constructor chains.

    Example:
        container = Container()
        container.register("event_bus", event_bus)
        container.register("config", config)

        bus = container.resolve("event_bus")
        cfg = container.resolve_typed("config", NexusConfig)
    """

    def __init__(self) -> None:
        self._instances: dict[str, Any] = {}
        self._factories: dict[str, Any] = {}

    def register(self, key: str, instance: Any) -> None:
        """Register a singleton instance."""
        self._instances[key] = instance
        logger.debug("DI: registered '%s' (%s)", key, type(instance).__name__)

    def register_factory(self, key: str, factory: Any) -> None:
        """Register a factory callable that creates an instance on first resolve."""
        self._factories[key] = factory
        logger.debug("DI: registered factory for '%s'", key)

    def resolve(self, key: str) -> Any:
        """Resolve an instance by key.

        If a factory is registered but no instance exists yet,
        the factory is called and the result is cached.
        """
        if key in self._instances:
            return self._instances[key]
        if key in self._factories:
            instance = self._factories[key]()
            self._instances[key] = instance
            del self._factories[key]
            logger.debug("DI: created '%s' from factory", key)
            return instance
        available = ", ".join(
            sorted(set(self._instances.keys()) | set(self._factories.keys()))
        ) or "(none)"
        raise KeyError(f"DI: '{key}' not registered. Available: {available}")

    def resolve_typed(self, key: str, expected_type: type[T]) -> T:
        """Resolve and type-check an instance."""
        instance = self.resolve(key)
        if not isinstance(instance, expected_type):
            raise TypeError(
                f"DI: '{key}' is {type(instance).__name__}, expected {expected_type.__name__}"
            )
        return instance

    def has(self, key: str) -> bool:
        """Check if a key is registered (instance or factory)."""
        return key in self._instances or key in self._factories

    def keys(self) -> list[str]:
        """List all registered keys."""
        return sorted(set(self._instances.keys()) | set(self._factories.keys()))

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __repr__(self) -> str:
        return f"Container(keys={self.keys()})"
