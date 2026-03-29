"""Telegram streamer — progressively edits a message as LLM chunks arrive."""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.enums import ChatAction

from nexusai.platforms.telegram.formatter import TelegramFormatter

logger = logging.getLogger(__name__)


class TelegramStreamer:
    """Stream LLM output into a single Telegram message via progressive edits.

    How it works:

    1. ``start()`` sends the initial placeholder message and begins
       sending the ``typing`` chat action in a background loop.
    2. ``append()`` buffers incoming text chunks and edits the message
       at the configured interval so Telegram rate-limits are respected.
    3. ``set_tool_status()`` shows a status line while a tool runs.
    4. ``finish()`` / ``error()`` send the final or error message and
       stop the typing indicator.

    All methods are safe to call concurrently from different tasks.
    """

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        *,
        edit_interval: float = 1.5,
        max_length: int = 4000,
        formatter: TelegramFormatter | None = None,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._edit_interval = edit_interval
        self._max_length = max_length
        self._formatter = formatter or TelegramFormatter()

        self._message_id: int | None = None
        self._buffer: list[str] = []
        self._tool_status: str | None = None
        self._last_edit: float = 0.0
        self._typing_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._finished = False

    # ── Public API ────────────────────────────────────────────────

    async def start(self, initial_text: str = "Processing...") -> int:
        """Send the initial placeholder message and start the typing indicator.

        Returns:
            The Telegram message ID of the placeholder.
        """
        msg = await self._bot.send_message(
            self._chat_id,
            initial_text,
            parse_mode="HTML",
        )
        self._message_id = msg.message_id
        self._start_typing()
        return msg.message_id

    async def append(self, text: str) -> None:
        """Append a chunk of text and edit the message if the interval has elapsed."""
        if self._finished:
            return

        async with self._lock:
            self._buffer.append(text)
            now = time.monotonic()
            if now - self._last_edit >= self._edit_interval:
                await self._do_edit()
                self._last_edit = now

    async def set_tool_status(self, tool_name: str) -> None:
        """Show a tool-usage status line below the streamed text."""
        self._tool_status = tool_name
        # Force an immediate edit so the user sees the tool status
        async with self._lock:
            await self._do_edit()
            self._last_edit = time.monotonic()

    async def finish(self, final_html: str) -> None:
        """Replace the message with the final formatted HTML and stop typing."""
        self._finished = True
        self._stop_typing()
        if not self._message_id:
            return

        # Split if the final text is too long
        parts = self._formatter.split_message(final_html)
        try:
            await self._bot.edit_message_text(
                text=parts[0],
                chat_id=self._chat_id,
                message_id=self._message_id,
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("Final edit failed, sending as new message")
            await self._bot.send_message(
                self._chat_id,
                parts[0],
                parse_mode="HTML",
            )

        # Send additional parts as new messages
        for part in parts[1:]:
            await self._bot.send_message(
                self._chat_id,
                part,
                parse_mode="HTML",
            )

    async def error(self, error_text: str) -> None:
        """Show an error message and stop typing."""
        escaped = self._formatter.escape(error_text)
        await self.finish(f"<b>Error:</b> {escaped}")

    # ── Internal helpers ──────────────────────────────────────────

    async def _do_edit(self) -> None:
        """Edit the message with the current buffer contents (caller holds the lock)."""
        if not self._message_id or not self._buffer:
            return

        full_text = "".join(self._buffer)
        display = self._formatter.escape(full_text)

        # Truncate from the front if too long, keeping the most recent output
        if len(display) > self._max_length:
            display = "..." + display[-(self._max_length - 3) :]

        if self._tool_status:
            status_line = (
                f"\n\n<i>Using: {self._formatter.escape(self._tool_status)}...</i>"
            )
            display += status_line

        try:
            await self._bot.edit_message_text(
                text=display,
                chat_id=self._chat_id,
                message_id=self._message_id,
                parse_mode="HTML",
            )
        except Exception:
            # Telegram may reject edits if content didn't change or rate limit hit
            logger.debug("Stream edit skipped (rate limit or no change)")

    def _start_typing(self) -> None:
        """Start a background task that sends ``typing`` action every 4 seconds."""
        if self._typing_task is None or self._typing_task.done():
            self._typing_task = asyncio.create_task(self._typing_loop())

    def _stop_typing(self) -> None:
        """Cancel the typing indicator background task."""
        if self._typing_task and not self._typing_task.done():
            self._typing_task.cancel()
            self._typing_task = None

    async def _typing_loop(self) -> None:
        """Send ``typing`` chat action every 4 seconds until cancelled."""
        try:
            while not self._finished:
                try:
                    await self._bot.send_chat_action(
                        self._chat_id, ChatAction.TYPING
                    )
                except Exception:
                    pass
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
