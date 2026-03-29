"""Slack platform adapter — slack-bolt async implementation of PlatformAdapter."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

try:
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    _SLACK_AVAILABLE = True
except ImportError:
    _SLACK_AVAILABLE = False

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
from nexusai.platforms.slack.formatter import SlackFormatter

logger = logging.getLogger(__name__)

# Debounce interval for streaming edits (seconds)
_STREAM_EDIT_INTERVAL = 0.5


class SlackAdapter(BasePlatformAdapter):
    """``PlatformAdapter`` implementation backed by slack-bolt async.

    Supports text, file uploads, interactive buttons (Block Kit actions),
    thread replies, and rich mrkdwn / Block Kit formatting.

    Args:
        bot_token:      Slack bot OAuth token (``xoxb-…``).
        signing_secret: Slack app signing secret for request verification.
        app_token:      Optional Socket Mode app token (``xapp-…``).
                        When provided, Socket Mode is used (no HTTP server
                        needed). If omitted, the adapter falls back to
                        HTTP mode on ``http_host:http_port``.
        event_bus:      NexusAI event bus.
        http_host:      HTTP handler host (default ``"0.0.0.0"``).
        http_port:      HTTP handler port (default ``3000``).

    Usage::

        adapter = SlackAdapter(bot_token, signing_secret, event_bus=bus)
        adapter.on_message(my_handler)
        await adapter.start()
    """

    CAPABILITIES = (
        PlatformCapability.TEXT
        | PlatformCapability.FILES
        | PlatformCapability.INLINE_BUTTONS
        | PlatformCapability.THREADS
        | PlatformCapability.RICH_FORMATTING
    )

    def __init__(
        self,
        bot_token: str,
        signing_secret: str,
        event_bus: EventBus,
        *,
        app_token: str | None = None,
        http_host: str = "0.0.0.0",
        http_port: int = 3000,
    ) -> None:
        if not _SLACK_AVAILABLE:
            raise ImportError(
                "slack-bolt is not installed. Install it with: pip install slack-bolt"
            )

        super().__init__(
            platform_name="slack",
            event_bus=event_bus,
            stream_edit_interval=_STREAM_EDIT_INTERVAL,
            max_message_length=4000,
        )

        self._bot_token = bot_token
        self._signing_secret = signing_secret
        self._app_token = app_token
        self._http_host = http_host
        self._http_port = http_port
        self._formatter = SlackFormatter()

        self._app: AsyncApp = AsyncApp(
            token=bot_token,
            signing_secret=signing_secret,
        )
        self._handler_task: asyncio.Task[None] | None = None
        self._socket_handler: Any | None = None

        # Register Slack event handlers on the bolt App
        self._app.event("message")(self._handle_message_event)
        self._app.action({"type": "button"})(self._handle_button_action)

    # ── PlatformAdapter protocol properties ───────────────────────

    @property
    def name(self) -> str:
        return "slack"

    @property
    def capabilities(self) -> int:
        return int(self.CAPABILITIES.value)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the Slack event listener.

        Uses Socket Mode when an ``app_token`` is configured; otherwise
        falls back to an HTTP server (useful for development with ngrok or
        in production behind a reverse proxy).
        """
        logger.info("Starting Slack adapter...")
        self._start_queue_consumer()

        if self._app_token:
            self._socket_handler = AsyncSocketModeHandler(self._app, self._app_token)
            self._handler_task = asyncio.create_task(self._run_socket_mode())
        else:
            self._handler_task = asyncio.create_task(self._run_http())

        logger.info("Slack adapter started")

    async def _run_socket_mode(self) -> None:
        """Run the Slack Socket Mode handler."""
        try:
            await self._socket_handler.start_async()
        except asyncio.CancelledError:
            logger.info("Slack socket mode task cancelled")
        except Exception:
            logger.exception("Slack socket mode task crashed")

    async def _run_http(self) -> None:
        """Run the Slack HTTP handler via bolt's built-in ASGI adapter."""
        try:
            await self._app.start_async(
                host=self._http_host,
                port=self._http_port,
            )
        except asyncio.CancelledError:
            logger.info("Slack HTTP handler task cancelled")
        except Exception:
            logger.exception("Slack HTTP handler task crashed")

    async def stop(self) -> None:
        """Gracefully shut down the Slack adapter."""
        logger.info("Stopping Slack adapter...")
        self._stop_queue_consumer()

        if self._socket_handler is not None:
            try:
                await self._socket_handler.close_async()
            except Exception:
                logger.debug("Socket handler close raised", exc_info=True)

        if self._handler_task and not self._handler_task.done():
            self._handler_task.cancel()
            try:
                await self._handler_task
            except asyncio.CancelledError:
                pass

        logger.info("Slack adapter stopped")

    # ── Slack event handlers ──────────────────────────────────────

    async def _handle_message_event(self, event: dict, say: Any) -> None:  # noqa: ARG002
        """Convert a Slack message event to IncomingMessage and dispatch."""
        # Ignore bot messages and message sub-types (edits, deletes, etc.)
        if event.get("bot_id") or event.get("subtype"):
            return

        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        text = event.get("text", "")
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts")

        user = PlatformUser(
            platform="slack",
            platform_user_id=user_id,
        )

        incoming = IncomingMessage(
            platform="slack",
            channel_id=channel_id,
            message_id=ts,
            user=user,
            text=text,
            thread_id=thread_ts,
            raw=event,
        )

        await self._dispatch_message(incoming)

    async def _handle_button_action(self, body: dict, ack: Any) -> None:
        """Handle a Slack interactive button click."""
        await ack()

        action = (body.get("actions") or [{}])[0]
        callback_data: str = action.get("value", action.get("action_id", ""))
        message_id: str = (body.get("message") or {}).get("ts", "")
        user_id: str = (body.get("user") or {}).get("id", "")

        user = PlatformUser(
            platform="slack",
            platform_user_id=user_id,
        )
        await self._dispatch_button_click(callback_data, message_id, user)

    # ── send_message ──────────────────────────────────────────────

    async def send_message(
        self,
        channel_id: str,
        message: OutgoingMessage,
    ) -> str:
        """Send a message to a Slack channel using Block Kit.

        Returns the Slack ``ts`` timestamp string, which doubles as
        the message ID for updates and thread replies.
        """
        blocks = self._formatter.to_blocks(message.text)

        # Append button actions block if present
        if message.buttons:
            blocks.append(self._build_actions_block(message.buttons))

        kwargs: dict[str, Any] = {
            "channel": channel_id,
            "text": message.text[:150],  # fallback text for notifications
            "blocks": blocks,
        }
        if message.thread_id:
            kwargs["thread_ts"] = message.thread_id

        result = await self._safe_execute(
            self._app.client.chat_postMessage(**kwargs),
            error_msg="Failed to send Slack message",
        )
        return result.get("ts", "")

    # ── edit_message ──────────────────────────────────────────────

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        message: OutgoingMessage,
    ) -> None:
        """Edit a previously sent Slack message (chat.update)."""
        blocks = self._formatter.to_blocks(message.text)

        await self._safe_execute(
            self._app.client.chat_update(
                channel=channel_id,
                ts=message_id,
                text=message.text[:150],
                blocks=blocks,
            ),
            error_msg="Failed to edit Slack message",
        )

    # ── delete_message ────────────────────────────────────────────

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> None:
        """Delete a Slack message (chat.delete)."""
        await self._safe_execute(
            self._app.client.chat_delete(
                channel=channel_id,
                ts=message_id,
            ),
            error_msg="Failed to delete Slack message",
        )

    # ── send_file ─────────────────────────────────────────────────

    async def send_file(
        self,
        channel_id: str,
        file: FileAttachment,
        caption: str | None = None,
    ) -> str:
        """Upload a file to a Slack channel."""
        if file.content is None:
            raise PlatformSendError("FileAttachment.content is required for Slack")

        result = await self._safe_execute(
            self._app.client.files_upload_v2(
                channel=channel_id,
                content=file.content,
                filename=file.filename,
                title=caption or file.filename,
            ),
            error_msg="Failed to upload Slack file",
        )
        return (result.get("file") or {}).get("id", "")

    # ── send_buttons ──────────────────────────────────────────────

    async def send_buttons(
        self,
        channel_id: str,
        text: str,
        buttons: list[list[ButtonAction]],
    ) -> str:
        """Send a message with interactive Block Kit buttons."""
        msg = OutgoingMessage(text=text, buttons=buttons)
        return await self.send_message(channel_id, msg)

    # ── stream_response ───────────────────────────────────────────

    async def stream_response(
        self,
        channel_id: str,
        chunks: AsyncGenerator[StreamChunk, None],
        initial_text: str = "Processing...",
    ) -> str:
        """Stream a response with debounced chat.update calls.

        Posts an initial message then progressively edits it as chunks
        arrive, throttled to one update per 0.5 seconds.
        Returns the message ``ts`` ID.
        """
        # Post initial message
        ts = await self.send_message(channel_id, OutgoingMessage(text=initial_text))

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
                    await self.edit_message(
                        channel_id, ts, OutgoingMessage(text=display)
                    )
                except Exception:
                    logger.debug("Slack stream edit throttled or failed, will retry")
                last_edit = now

        # Final update
        full_text = "".join(buffer)
        if full_text:
            display = full_text
            if len(display) > self._formatter.max_message_length:
                display = display[-self._formatter.max_message_length :]
            try:
                await self.edit_message(
                    channel_id, ts, OutgoingMessage(text=display)
                )
            except Exception:
                logger.warning("Final Slack stream edit failed")

        return ts

    # ── get_user_info ─────────────────────────────────────────────

    async def get_user_info(self, platform_user_id: str) -> PlatformUser:
        """Resolve a Slack user by their user ID."""
        try:
            result = await self._app.client.users_info(user=platform_user_id)
            profile = (result.get("user") or {}).get("profile") or {}
            user_obj = result.get("user") or {}
            return PlatformUser(
                platform="slack",
                platform_user_id=platform_user_id,
                username=user_obj.get("name"),
                display_name=profile.get("display_name") or profile.get("real_name"),
            )
        except Exception:
            return PlatformUser(
                platform="slack",
                platform_user_id=platform_user_id,
            )

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _build_actions_block(buttons: list[list[ButtonAction]]) -> dict:
        """Convert NexusAI button rows into a Slack Block Kit ``actions`` block."""
        elements: list[dict] = []
        for row in buttons:
            for btn in row:
                if btn.url:
                    elements.append(
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": btn.text},
                            "url": btn.url,
                            "action_id": btn.callback_data,
                        }
                    )
                else:
                    elements.append(
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": btn.text},
                            "value": btn.callback_data,
                            "action_id": btn.callback_data,
                        }
                    )
        return {"type": "actions", "elements": elements}
