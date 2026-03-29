"""Base platform adapter with shared streaming, error-handling, and message-buffering logic."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any, Awaitable, Callable

from nexusai.core.errors import PlatformError, PlatformSendError
from nexusai.core.events import EventBus, MessageReceived, MessageSent
from nexusai.core.types import (
    IncomingMessage,
    OutgoingMessage,
    PlatformUser,
    StreamChunk,
)

logger = logging.getLogger(__name__)


class BasePlatformAdapter:
    """Shared logic for all platform adapters.

    Subclasses implement the transport-specific ``send_message``,
    ``edit_message``, ``send_file``, and ``send_buttons`` methods;
    this base class provides:

    * **Debounced streaming edits** — ``_stream_with_edits`` collects
      ``StreamChunk``s and edits the sent message at a configurable
      interval so Telegram / Discord rate-limits are respected.
    * **Common error handling** — ``_safe_execute`` wraps any async call,
      catches exceptions, and converts them to ``PlatformSendError``.
    * **Message queue management** — an internal asyncio.Queue with a
      background consumer that serialises outgoing messages.
    * **Callback registry** — ``on_message`` / ``on_button_click`` store
      callbacks the handlers invoke when events arrive.
    """

    def __init__(
        self,
        platform_name: str,
        event_bus: EventBus,
        *,
        stream_edit_interval: float = 1.5,
        max_message_length: int = 4096,
    ) -> None:
        self.platform_name = platform_name
        self.event_bus = event_bus
        self.stream_edit_interval = stream_edit_interval
        self.max_message_length = max_message_length

        # Callback registries
        self._message_callbacks: list[Callable[[IncomingMessage], Awaitable[None]]] = []
        self._button_callbacks: list[
            Callable[[str, str, PlatformUser], Awaitable[None]]
        ] = []

        # Outgoing message queue
        self._outgoing_queue: asyncio.Queue[tuple[str, OutgoingMessage]] = asyncio.Queue()
        self._queue_task: asyncio.Task[None] | None = None

    # ── Callback registration ─────────────────────────────────────

    def on_message(
        self,
        callback: Callable[[IncomingMessage], Awaitable[None]],
    ) -> None:
        """Register a callback invoked for every incoming message."""
        self._message_callbacks.append(callback)

    def on_button_click(
        self,
        callback: Callable[[str, str, PlatformUser], Awaitable[None]],
    ) -> None:
        """Register a callback invoked when a user presses an inline button.

        Args:
            callback: ``async def handler(callback_data, message_id, user)``
        """
        self._button_callbacks.append(callback)

    # ── Dispatch helpers ──────────────────────────────────────────

    async def _dispatch_message(self, message: IncomingMessage) -> None:
        """Fan-out an incoming message to all registered callbacks."""
        await self.event_bus.publish(
            MessageReceived(
                source=self.platform_name,
                platform=self.platform_name,
                channel_id=message.channel_id,
                user_id=message.user.platform_user_id,
                text=message.text,
                thread_id=message.thread_id,
            )
        )
        for cb in self._message_callbacks:
            try:
                await cb(message)
            except Exception:
                logger.exception("Message callback error on %s", self.platform_name)

    async def _dispatch_button_click(
        self,
        callback_data: str,
        message_id: str,
        user: PlatformUser,
    ) -> None:
        """Fan-out a button click to all registered callbacks."""
        for cb in self._button_callbacks:
            try:
                await cb(callback_data, message_id, user)
            except Exception:
                logger.exception("Button callback error on %s", self.platform_name)

    # ── Error handling ────────────────────────────────────────────

    async def _safe_execute(
        self,
        coro: Any,
        *,
        error_msg: str = "Platform operation failed",
    ) -> Any:
        """Execute an awaitable, converting exceptions to ``PlatformSendError``."""
        try:
            return await coro
        except PlatformError:
            raise
        except Exception as exc:
            logger.exception("%s on %s: %s", error_msg, self.platform_name, exc)
            raise PlatformSendError(f"{error_msg}: {exc}") from exc

    # ── Streaming with debounced edits ────────────────────────────

    async def _stream_with_edits(
        self,
        channel_id: str,
        chunks: AsyncGenerator[StreamChunk, None],
        initial_text: str = "Processing...",
        edit_fn: Callable[[str, str, OutgoingMessage], Awaitable[None]] | None = None,
        send_fn: Callable[[str, OutgoingMessage], Awaitable[str]] | None = None,
        formatter_escape: Callable[[str], str] | None = None,
    ) -> str:
        """Collect ``StreamChunk``s and edit the message at intervals.

        This prevents hitting platform rate-limits while still giving
        the user responsive streaming feedback.

        Args:
            channel_id: Where to send the message.
            chunks: Async generator yielding ``StreamChunk`` objects.
            initial_text: Text shown while the first chunk arrives.
            edit_fn: Platform-specific message edit callable.
            send_fn: Platform-specific message send callable.
            formatter_escape: Optional HTML/markdown escape function.

        Returns:
            The platform message ID of the final message.
        """
        if send_fn is None or edit_fn is None:
            raise PlatformSendError("send_fn and edit_fn are required for streaming")

        escape = formatter_escape or (lambda t: t)

        # Send the initial "thinking" message
        msg = OutgoingMessage(text=initial_text, parse_mode="html")
        message_id = await send_fn(channel_id, msg)

        buffer: list[str] = []
        tool_status: str | None = None
        last_edit_time = time.monotonic()

        async for chunk in chunks:
            if chunk.is_final:
                # Final chunk — the caller should format the final message
                if chunk.text:
                    buffer.append(chunk.text)
                break

            if chunk.tool_name:
                tool_status = chunk.tool_name

            if chunk.text:
                buffer.append(chunk.text)

            # Debounce: only edit when enough time has passed
            now = time.monotonic()
            if now - last_edit_time >= self.stream_edit_interval and buffer:
                display = escape("".join(buffer))
                if tool_status:
                    display += f"\n\n<i>Using: {escape(tool_status)}...</i>"
                if len(display) > self.max_message_length:
                    display = display[-self.max_message_length :]
                try:
                    await edit_fn(
                        channel_id,
                        message_id,
                        OutgoingMessage(text=display, parse_mode="html"),
                    )
                except Exception:
                    logger.debug("Edit throttled or failed, will retry next interval")
                last_edit_time = now

        # Final edit with complete text
        full_text = "".join(buffer)
        if full_text:
            display = escape(full_text)
            if len(display) > self.max_message_length:
                display = display[-self.max_message_length :]
            try:
                await edit_fn(
                    channel_id,
                    message_id,
                    OutgoingMessage(text=display, parse_mode="html"),
                )
            except Exception:
                logger.warning("Final streaming edit failed")

        return message_id

    # ── Message queue ─────────────────────────────────────────────

    def _start_queue_consumer(self) -> None:
        """Start the background task that drains the outgoing message queue."""
        if self._queue_task is None or self._queue_task.done():
            self._queue_task = asyncio.create_task(self._consume_queue())

    async def _consume_queue(self) -> None:
        """Background consumer — sends queued messages one at a time."""
        while True:
            channel_id, message = await self._outgoing_queue.get()
            try:
                await self.send_message(channel_id, message)  # type: ignore[attr-defined]
            except Exception:
                logger.exception("Queued message send failed")
            finally:
                self._outgoing_queue.task_done()

    async def enqueue_message(self, channel_id: str, message: OutgoingMessage) -> None:
        """Add a message to the outgoing queue for serial delivery."""
        await self._outgoing_queue.put((channel_id, message))

    def _stop_queue_consumer(self) -> None:
        """Cancel the background queue consumer task."""
        if self._queue_task and not self._queue_task.done():
            self._queue_task.cancel()
            self._queue_task = None
