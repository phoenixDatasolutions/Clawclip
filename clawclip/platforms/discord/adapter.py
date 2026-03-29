"""Discord platform adapter — discord.py implementation of PlatformAdapter."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

try:
    import discord
    import discord.ext.commands  # noqa: F401 — ensure commands extension is importable

    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False

from clawclip.core.enums import PlatformCapability
from clawclip.core.errors import PlatformConnectionError, PlatformSendError
from clawclip.core.events import EventBus
from clawclip.core.types import (
    ButtonAction,
    FileAttachment,
    IncomingMessage,
    OutgoingMessage,
    PlatformUser,
    StreamChunk,
)
from clawclip.platforms.base import BasePlatformAdapter
from clawclip.platforms.discord.formatter import DiscordFormatter

logger = logging.getLogger(__name__)

# Debounce interval for streaming edits (seconds)
_STREAM_EDIT_INTERVAL = 0.5


class DiscordAdapter(BasePlatformAdapter):
    """``PlatformAdapter`` implementation backed by discord.py.

    Supports text, file uploads, inline buttons (discord.ui.View), reactions,
    threads, and rich markdown formatting.

    Args:
        token:          Discord bot token.
        event_bus:      ClawClip event bus for publishing incoming events.
        allowed_guilds: If non-empty, only process messages from these guild IDs.

    Usage::

        adapter = DiscordAdapter(token, event_bus, allowed_guilds=[123456])
        adapter.on_message(my_handler)
        await adapter.start()
    """

    CAPABILITIES = (
        PlatformCapability.TEXT
        | PlatformCapability.FILES
        | PlatformCapability.INLINE_BUTTONS
        | PlatformCapability.REACTIONS
        | PlatformCapability.THREADS
        | PlatformCapability.RICH_FORMATTING
    )

    def __init__(
        self,
        token: str,
        event_bus: EventBus,
        allowed_guilds: list[int] | None = None,
    ) -> None:
        if not _DISCORD_AVAILABLE:
            raise ImportError(
                "discord.py is not installed. Install it with: pip install discord.py"
            )

        super().__init__(
            platform_name="discord",
            event_bus=event_bus,
            stream_edit_interval=_STREAM_EDIT_INTERVAL,
            max_message_length=2000,
        )
        self._token = token
        self._allowed_guilds: set[int] = set(allowed_guilds or [])
        self._formatter = DiscordFormatter()

        # discord.py client — created in __init__ so type checkers are happy
        intents = discord.Intents.default()
        intents.message_content = True
        self._bot: discord.Client = discord.Client(intents=intents)
        self._bot_task: asyncio.Task[None] | None = None

        # Wire up discord.py event handlers
        self._bot.event(self._on_ready)
        self._bot.event(self._on_message)

    # ── PlatformAdapter protocol properties ───────────────────────

    @property
    def name(self) -> str:
        return "discord"

    @property
    def capabilities(self) -> int:
        return int(self.CAPABILITIES.value)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Discord and start receiving events."""
        logger.info("Starting Discord adapter...")
        self._start_queue_consumer()
        self._bot_task = asyncio.create_task(self._run_bot())
        logger.info("Discord adapter started")

    async def _run_bot(self) -> None:
        """Background task that keeps the bot connected."""
        try:
            await self._bot.start(self._token)
        except asyncio.CancelledError:
            logger.info("Discord bot task cancelled")
        except Exception:
            logger.exception("Discord bot task crashed")

    async def stop(self) -> None:
        """Gracefully disconnect from Discord."""
        logger.info("Stopping Discord adapter...")
        self._stop_queue_consumer()

        await self._bot.close()

        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass

        logger.info("Discord adapter stopped")

    # ── Discord event handlers ────────────────────────────────────

    async def _on_ready(self) -> None:
        logger.info("Discord bot logged in as %s", self._bot.user)

    async def _on_message(self, message: discord.Message) -> None:
        """Convert a discord.Message into an IncomingMessage and dispatch it."""
        # Ignore the bot's own messages
        if message.author == self._bot.user:
            return

        # Honour guild allow-list if configured
        if self._allowed_guilds and message.guild:
            if message.guild.id not in self._allowed_guilds:
                return

        thread_id: str | None = None
        if isinstance(message.channel, discord.Thread):
            thread_id = str(message.channel.id)

        user = PlatformUser(
            platform="discord",
            platform_user_id=str(message.author.id),
            username=message.author.name,
            display_name=getattr(message.author, "display_name", None),
        )

        incoming = IncomingMessage(
            platform="discord",
            channel_id=str(message.channel.id),
            message_id=str(message.id),
            user=user,
            text=message.content,
            thread_id=thread_id,
            raw={"guild_id": str(message.guild.id) if message.guild else None},
        )

        await self._dispatch_message(incoming)

    # ── send_message ──────────────────────────────────────────────

    async def send_message(
        self,
        channel_id: str,
        message: OutgoingMessage,
    ) -> str:
        """Send a text message to a Discord channel.

        Splits messages that exceed Discord's 2000-character limit.
        Returns the message ID of the last sent chunk.
        """
        channel = await self._fetch_channel(channel_id)

        view: discord.ui.View | None = None
        if message.buttons:
            from clawclip.platforms.discord.views import ButtonView

            async def _button_cb(callback_data: str, user_id: str) -> None:
                await self._dispatch_button_click(callback_data, channel_id, _make_platform_user(user_id))

            view = ButtonView(message.buttons, _button_cb)

        parts = self._formatter.split_message(message.text)
        last_msg_id = ""

        for i, part in enumerate(parts):
            v = view if i == len(parts) - 1 else None
            result = await self._safe_execute(
                channel.send(content=part, view=v),
                error_msg="Failed to send Discord message",
            )
            last_msg_id = str(result.id)

        return last_msg_id

    # ── edit_message ──────────────────────────────────────────────

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        message: OutgoingMessage,
    ) -> None:
        """Edit a previously sent Discord message."""
        channel = await self._fetch_channel(channel_id)
        text = message.text
        if len(text) > self._formatter.max_message_length:
            text = text[-self._formatter.max_message_length :]

        msg = await self._safe_execute(
            channel.fetch_message(int(message_id)),
            error_msg="Failed to fetch Discord message for edit",
        )
        await self._safe_execute(
            msg.edit(content=text),
            error_msg="Failed to edit Discord message",
        )

    # ── delete_message ────────────────────────────────────────────

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> None:
        """Delete a Discord message."""
        channel = await self._fetch_channel(channel_id)
        msg = await self._safe_execute(
            channel.fetch_message(int(message_id)),
            error_msg="Failed to fetch Discord message for deletion",
        )
        await self._safe_execute(
            msg.delete(),
            error_msg="Failed to delete Discord message",
        )

    # ── send_file ─────────────────────────────────────────────────

    async def send_file(
        self,
        channel_id: str,
        file: FileAttachment,
        caption: str | None = None,
    ) -> str:
        """Send a file attachment to a Discord channel.

        The file content is wrapped in a ``discord.File`` backed by
        an in-memory ``io.BytesIO`` buffer.
        """
        if file.content is None:
            raise PlatformSendError("FileAttachment.content is required for Discord")

        channel = await self._fetch_channel(channel_id)
        discord_file = discord.File(
            io.BytesIO(file.content),
            filename=file.filename,
        )
        result = await self._safe_execute(
            channel.send(content=caption, file=discord_file),
            error_msg="Failed to send Discord file",
        )
        return str(result.id)

    # ── send_buttons ──────────────────────────────────────────────

    async def send_buttons(
        self,
        channel_id: str,
        text: str,
        buttons: list[list[ButtonAction]],
    ) -> str:
        """Send a message with interactive discord.ui.Button components."""
        msg = OutgoingMessage(text=text, buttons=buttons)
        return await self.send_message(channel_id, msg)

    # ── stream_response ───────────────────────────────────────────

    async def stream_response(
        self,
        channel_id: str,
        chunks: AsyncGenerator[StreamChunk, None],
        initial_text: str = "Processing...",
    ) -> str:
        """Stream a response with debounced message edits.

        Sends an initial message, then edits it as chunks arrive, throttled
        to at most one edit every 0.5 seconds to respect Discord rate limits.
        Returns the message ID of the streamed message.
        """
        channel = await self._fetch_channel(channel_id)

        # Send the initial placeholder
        init_msg = await self._safe_execute(
            channel.send(content=initial_text),
            error_msg="Failed to send initial Discord stream message",
        )
        message_id = str(init_msg.id)

        buffer: list[str] = []
        last_edit = time.monotonic()

        async for chunk in chunks:
            if chunk.is_final:
                if chunk.text:
                    buffer.append(chunk.text)
                break

            if chunk.text:
                buffer.append(chunk.text)

            now = time.monotonic()
            if now - last_edit >= _STREAM_EDIT_INTERVAL and buffer:
                display = "".join(buffer)
                if len(display) > self._formatter.max_message_length:
                    display = display[-self._formatter.max_message_length :]
                try:
                    await init_msg.edit(content=display)
                except Exception:
                    logger.debug("Discord stream edit throttled or failed, will retry")
                last_edit = now

        # Final edit
        full_text = "".join(buffer)
        if full_text:
            display = full_text
            if len(display) > self._formatter.max_message_length:
                display = display[-self._formatter.max_message_length :]
            try:
                await init_msg.edit(content=display)
            except Exception:
                logger.warning("Final Discord stream edit failed")

        return message_id

    # ── get_user_info ─────────────────────────────────────────────

    async def get_user_info(self, platform_user_id: str) -> PlatformUser:
        """Resolve a Discord user by their snowflake ID."""
        try:
            user = await self._bot.fetch_user(int(platform_user_id))
            return PlatformUser(
                platform="discord",
                platform_user_id=platform_user_id,
                username=user.name,
                display_name=user.display_name,
            )
        except Exception:
            return PlatformUser(
                platform="discord",
                platform_user_id=platform_user_id,
            )

    # ── Internal helpers ──────────────────────────────────────────

    async def _fetch_channel(self, channel_id: str) -> Any:
        """Fetch a Discord channel object by ID.

        Raises ``PlatformConnectionError`` if the bot is not ready or the
        channel cannot be found.
        """
        if not self._bot.is_ready():
            raise PlatformConnectionError("Discord bot is not connected — call start() first")

        channel = self._bot.get_channel(int(channel_id))
        if channel is None:
            channel = await self._safe_execute(
                self._bot.fetch_channel(int(channel_id)),
                error_msg=f"Failed to fetch Discord channel {channel_id}",
            )
        return channel


def _make_platform_user(user_id: str) -> PlatformUser:
    """Create a minimal PlatformUser from a Discord user ID."""
    return PlatformUser(
        platform="discord",
        platform_user_id=user_id,
    )
