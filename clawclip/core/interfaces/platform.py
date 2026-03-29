"""Platform Adapter protocol — interface every messaging platform must implement."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from clawclip.core.types import (
    ButtonAction,
    FileAttachment,
    IncomingMessage,
    OutgoingMessage,
    PlatformUser,
    StreamChunk,
)


@runtime_checkable
class PlatformAdapter(Protocol):
    """Interface every messaging platform must implement.

    Implementations: TelegramAdapter, DiscordAdapter, SlackAdapter, etc.
    """

    @property
    def name(self) -> str:
        """Unique platform identifier (e.g., 'telegram', 'discord')."""
        ...

    @property
    def capabilities(self) -> int:
        """PlatformCapability flags declaring what this platform supports."""
        ...

    async def start(self) -> None:
        """Start listening for incoming messages."""
        ...

    async def stop(self) -> None:
        """Gracefully shut down the adapter."""
        ...

    async def send_message(
        self,
        channel_id: str,
        message: OutgoingMessage,
    ) -> str:
        """Send a message. Returns the platform-specific message ID."""
        ...

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        message: OutgoingMessage,
    ) -> None:
        """Edit a previously sent message (if supported)."""
        ...

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> None:
        """Delete a message."""
        ...

    async def send_file(
        self,
        channel_id: str,
        file: FileAttachment,
        caption: str | None = None,
    ) -> str:
        """Send a file. Returns message ID."""
        ...

    async def send_buttons(
        self,
        channel_id: str,
        text: str,
        buttons: list[list[ButtonAction]],
    ) -> str:
        """Send a message with action buttons (if supported)."""
        ...

    async def stream_response(
        self,
        channel_id: str,
        chunks: AsyncGenerator[StreamChunk, None],
        initial_text: str = "Processing...",
    ) -> str:
        """Stream a response with progressive edits. Returns final message ID."""
        ...

    def on_message(
        self,
        callback: Callable[[IncomingMessage], Awaitable[None]],
    ) -> None:
        """Register a callback for incoming messages."""
        ...

    def on_button_click(
        self,
        callback: Callable[[str, str, PlatformUser], Awaitable[None]],
    ) -> None:
        """Register a callback for button clicks.

        Args: callback(callback_data, message_id, user)
        """
        ...

    async def get_user_info(self, platform_user_id: str) -> PlatformUser:
        """Resolve a user on this platform."""
        ...
