"""Storage Backend protocol — abstraction over the persistence layer."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Abstraction over the persistence layer.

    Implementations use SQLAlchemy repositories underneath,
    but this protocol keeps the core decoupled from ORM details.
    """

    async def initialize(self) -> None:
        """Initialize the storage backend (create tables, etc.)."""
        ...

    async def shutdown(self) -> None:
        """Close connections and clean up."""
        ...

    # ── User Operations ─────────────────────────────────────────

    async def get_user(self, platform: str, platform_user_id: str) -> dict[str, Any] | None:
        """Look up a user by their platform identity."""
        ...

    async def create_user(self, user_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new user record."""
        ...

    async def update_user(self, user_id: str, updates: dict[str, Any]) -> None:
        """Update an existing user record."""
        ...

    # ── Conversation Operations ─────────────────────────────────

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Get a conversation by ID."""
        ...

    async def create_conversation(self, conv_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new conversation."""
        ...

    async def append_message(
        self, conversation_id: str, message: dict[str, Any]
    ) -> None:
        """Append a message to a conversation."""
        ...

    async def list_conversations(
        self,
        user_id: str,
        platform: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List conversations for a user."""
        ...

    # ── Generic Key-Value State ─────────────────────────────────

    async def get_state(self, namespace: str, key: str) -> Any | None:
        """Get a value from the key-value store."""
        ...

    async def set_state(self, namespace: str, key: str, value: Any) -> None:
        """Set a value in the key-value store."""
        ...

    async def delete_state(self, namespace: str, key: str) -> None:
        """Delete a value from the key-value store."""
        ...
