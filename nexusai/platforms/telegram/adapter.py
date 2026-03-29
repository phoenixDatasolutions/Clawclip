"""Telegram platform adapter — aiogram 3.x implementation of PlatformAdapter."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, Awaitable, Callable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from nexusai.core.enums import PlatformCapability
from nexusai.core.errors import PlatformConnectionError, PlatformSendError
from nexusai.core.events import EventBus
from nexusai.core.types import (
    ButtonAction,
    FileAttachment,
    IncomingMessage,
    OutgoingMessage,
    PlatformUser,
    StreamChunk,
)
from nexusai.platforms.base import BasePlatformAdapter
from nexusai.platforms.telegram.formatter import TelegramFormatter
from nexusai.platforms.telegram.handlers import build_router
from nexusai.platforms.telegram.streamer import TelegramStreamer

logger = logging.getLogger(__name__)


class TelegramAdapter(BasePlatformAdapter):
    """``PlatformAdapter`` implementation backed by aiogram 3.x.

    Config dict keys:
        bot_token (str):          Telegram Bot API token.
        allowed_user_ids (list):  Telegram user IDs allowed to interact.
        stream_edit_interval (float): Seconds between streaming edits (default 1.5).
        max_message_length (int): Truncation limit (default 4000).

    Usage::

        adapter = TelegramAdapter(config, event_bus)
        adapter.on_message(my_handler)
        await adapter.start()   # blocks until stopped
    """

    # ── Platform identity ─────────────────────────────────────────

    CAPABILITIES = (
        PlatformCapability.TEXT
        | PlatformCapability.FILES
        | PlatformCapability.INLINE_BUTTONS
        | PlatformCapability.STREAMING_EDITS
        | PlatformCapability.RICH_FORMATTING
        | PlatformCapability.IMAGES
    )

    def __init__(self, config: dict[str, Any], event_bus: EventBus) -> None:
        super().__init__(
            platform_name="telegram",
            event_bus=event_bus,
            stream_edit_interval=config.get("stream_edit_interval", 1.5),
            max_message_length=config.get("max_message_length", 4000),
        )
        self._config = config
        self._bot_token: str = config["bot_token"]
        self._allowed_user_ids: set[int] = set(config.get("allowed_user_ids", []))

        self._bot: Bot | None = None
        self._dp: Dispatcher | None = None
        self._polling_task: asyncio.Task[None] | None = None
        self._formatter = TelegramFormatter()

    # ── PlatformAdapter protocol properties ───────────────────────

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def capabilities(self) -> int:
        return self.CAPABILITIES.value  # type: ignore[return-value]

    @property
    def bot(self) -> Bot:
        """Return the underlying ``aiogram.Bot`` instance (for handlers)."""
        if self._bot is None:
            raise PlatformConnectionError("Bot not initialised — call start() first")
        return self._bot

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Create the Bot and Dispatcher, register handlers, and start polling."""
        logger.info("Starting Telegram adapter...")

        self._bot = Bot(
            token=self._bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self._dp = Dispatcher(storage=MemoryStorage())

        # Wire up the handler router
        router = build_router(self)
        self._dp.include_router(router)

        # Start the outgoing-message queue consumer
        self._start_queue_consumer()

        # Start long-polling in a background task so start() is non-blocking
        self._polling_task = asyncio.create_task(self._run_polling())
        logger.info("Telegram adapter started — polling for updates")

    async def _run_polling(self) -> None:
        """Internal: run dispatcher polling (runs until cancelled)."""
        if self._dp is None or self._bot is None:
            return
        try:
            await self._dp.start_polling(self._bot)
        except asyncio.CancelledError:
            logger.info("Telegram polling cancelled")
        except Exception:
            logger.exception("Telegram polling crashed")

    async def stop(self) -> None:
        """Gracefully shut down polling and close the bot session."""
        logger.info("Stopping Telegram adapter...")
        self._stop_queue_consumer()

        if self._dp:
            await self._dp.stop_polling()

        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass

        if self._bot:
            await self._bot.session.close()
            self._bot = None

        self._dp = None
        logger.info("Telegram adapter stopped")

    # ── send_message ──────────────────────────────────────────────

    async def send_message(
        self,
        channel_id: str,
        message: OutgoingMessage,
    ) -> str:
        """Send a text message to a Telegram chat.

        Returns the Telegram message ID as a string.
        """
        bot = self.bot
        parse_mode = (message.parse_mode or "html").upper()
        if parse_mode not in ("HTML", "MARKDOWN", "MARKDOWNV2"):
            parse_mode = "HTML"

        # Build optional inline keyboard from message buttons
        reply_markup = self._build_markup(message.buttons) if message.buttons else None

        # Split long messages
        parts = self._formatter.split_message(message.text)
        last_msg_id = ""

        for i, part in enumerate(parts):
            markup = reply_markup if i == len(parts) - 1 else None
            result = await self._safe_execute(
                bot.send_message(
                    chat_id=int(channel_id),
                    text=part,
                    parse_mode=parse_mode,
                    reply_markup=markup,
                ),
                error_msg="Failed to send Telegram message",
            )
            last_msg_id = str(result.message_id)

        return last_msg_id

    # ── edit_message ──────────────────────────────────────────────

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        message: OutgoingMessage,
    ) -> None:
        """Edit a previously sent Telegram message."""
        bot = self.bot
        parse_mode = (message.parse_mode or "html").upper()
        if parse_mode not in ("HTML", "MARKDOWN", "MARKDOWNV2"):
            parse_mode = "HTML"

        reply_markup = self._build_markup(message.buttons) if message.buttons else None

        # Truncate if needed
        text = message.text
        if len(text) > self._formatter.MAX_LENGTH:
            text = text[: self._formatter.MAX_LENGTH]

        await self._safe_execute(
            bot.edit_message_text(
                text=text,
                chat_id=int(channel_id),
                message_id=int(message_id),
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            ),
            error_msg="Failed to edit Telegram message",
        )

    # ── delete_message ────────────────────────────────────────────

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> None:
        """Delete a Telegram message."""
        await self._safe_execute(
            self.bot.delete_message(
                chat_id=int(channel_id),
                message_id=int(message_id),
            ),
            error_msg="Failed to delete Telegram message",
        )

    # ── send_file ─────────────────────────────────────────────────

    async def send_file(
        self,
        channel_id: str,
        file: FileAttachment,
        caption: str | None = None,
    ) -> str:
        """Send a file (document) to a Telegram chat."""
        bot = self.bot

        if file.content is None:
            raise PlatformSendError("FileAttachment.content is required for Telegram")

        doc = BufferedInputFile(file.content, filename=file.filename)
        result = await self._safe_execute(
            bot.send_document(
                chat_id=int(channel_id),
                document=doc,
                caption=caption,
                parse_mode="HTML",
            ),
            error_msg="Failed to send Telegram document",
        )
        return str(result.message_id)

    # ── send_buttons ──────────────────────────────────────────────

    async def send_buttons(
        self,
        channel_id: str,
        text: str,
        buttons: list[list[ButtonAction]],
    ) -> str:
        """Send a message with inline keyboard buttons."""
        markup = self._build_markup(buttons)
        result = await self._safe_execute(
            self.bot.send_message(
                chat_id=int(channel_id),
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            ),
            error_msg="Failed to send Telegram buttons",
        )
        return str(result.message_id)

    # ── stream_response ───────────────────────────────────────────

    async def stream_response(
        self,
        channel_id: str,
        chunks: AsyncGenerator[StreamChunk, None],
        initial_text: str = "Processing...",
    ) -> str:
        """Stream an LLM response with debounced message edits.

        Uses ``TelegramStreamer`` to progressively update a single Telegram
        message as chunks arrive, editing at most every 1.5 seconds.
        """
        streamer = TelegramStreamer(
            bot=self.bot,
            chat_id=int(channel_id),
            edit_interval=self.stream_edit_interval,
            max_length=self.max_message_length,
            formatter=self._formatter,
        )
        await streamer.start(initial_text)

        final_parts: list[str] = []
        try:
            async for chunk in chunks:
                if chunk.tool_name:
                    await streamer.set_tool_status(chunk.tool_name)
                if chunk.text:
                    final_parts.append(chunk.text)
                    await streamer.append(chunk.text)
                if chunk.is_final:
                    break
        except Exception as exc:
            logger.exception("Streaming error")
            await streamer.error(str(exc))
            return ""

        # Build final message
        full_text = "".join(final_parts)
        escaped = self._formatter.escape(full_text) if full_text else "(no response)"
        await streamer.finish(escaped)
        return str(streamer._message_id or "")

    # ── get_user_info ─────────────────────────────────────────────

    async def get_user_info(self, platform_user_id: str) -> PlatformUser:
        """Resolve a Telegram user by ID."""
        try:
            chat = await self.bot.get_chat(int(platform_user_id))
            return PlatformUser(
                platform="telegram",
                platform_user_id=platform_user_id,
                username=chat.username,
                display_name=chat.full_name,
            )
        except Exception:
            return PlatformUser(
                platform="telegram",
                platform_user_id=platform_user_id,
            )

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _build_markup(
        buttons: list[list[ButtonAction]] | None,
    ) -> InlineKeyboardMarkup | None:
        """Convert NexusAI ``ButtonAction`` rows to aiogram ``InlineKeyboardMarkup``."""
        if not buttons:
            return None
        rows: list[list[InlineKeyboardButton]] = []
        for row in buttons:
            kb_row: list[InlineKeyboardButton] = []
            for btn in row:
                if btn.url:
                    kb_row.append(
                        InlineKeyboardButton(text=btn.text, url=btn.url)
                    )
                else:
                    kb_row.append(
                        InlineKeyboardButton(
                            text=btn.text, callback_data=btn.callback_data
                        )
                    )
            rows.append(kb_row)
        return InlineKeyboardMarkup(inline_keyboard=rows)
