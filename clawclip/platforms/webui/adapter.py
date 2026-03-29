"""WebUI platform adapter — WebSocket-based browser chat platform."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

try:
    import uvicorn
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

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
from clawclip.platforms.webui.formatter import WebUIFormatter

logger = logging.getLogger(__name__)

# Debounce interval for streaming edits (seconds)
_STREAM_EDIT_INTERVAL = 0.5


class WebUIAdapter(BasePlatformAdapter):
    """``PlatformAdapter`` implementation backed by a FastAPI / WebSocket server.

    Each browser tab connects to ``/ws/chat/{session_id}``.  The session_id
    doubles as the ``channel_id`` used by the rest of the platform layer.

    Args:
        host:      Host to bind the HTTP/WS server on (default ``"0.0.0.0"``).
        port:      Port to listen on (default ``8080``).
        event_bus: ClawClip event bus.

    Usage::

        adapter = WebUIAdapter(host="0.0.0.0", port=8080, event_bus=bus)
        adapter.on_message(my_handler)
        await adapter.start()
    """

    CAPABILITIES = (
        PlatformCapability.TEXT
        | PlatformCapability.FILES
        | PlatformCapability.INLINE_BUTTONS
        | PlatformCapability.STREAMING_EDITS
        | PlatformCapability.RICH_FORMATTING
    )

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        event_bus: EventBus | None = None,
    ) -> None:
        if not _FASTAPI_AVAILABLE:
            raise ImportError(
                "fastapi and uvicorn are not installed. "
                "Install them with: pip install fastapi uvicorn[standard]"
            )

        if event_bus is None:
            raise ValueError("event_bus is required")

        super().__init__(
            platform_name="webui",
            event_bus=event_bus,
            stream_edit_interval=_STREAM_EDIT_INTERVAL,
            max_message_length=50_000,
        )

        self._host = host
        self._port = port
        self._formatter = WebUIFormatter()

        # session_id -> WebSocket mapping for connected clients
        self._clients: dict[str, WebSocket] = {}

        self._app: FastAPI = self._build_app()
        self._server_task: asyncio.Task[None] | None = None

    # ── PlatformAdapter protocol properties ───────────────────────

    @property
    def name(self) -> str:
        return "webui"

    @property
    def capabilities(self) -> int:
        return int(self.CAPABILITIES.value)

    # ── FastAPI app ───────────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        """Construct the FastAPI application with the WebSocket endpoint."""
        app = FastAPI(title="ClawClip WebUI", docs_url=None, redoc_url=None)

        @app.get("/health")
        async def health() -> dict:
            return {"status": "ok", "clients": len(self._clients)}

        @app.websocket("/ws/chat/{session_id}")
        async def ws_endpoint(websocket: WebSocket, session_id: str) -> None:
            await self._handle_websocket(websocket, session_id)

        return app

    async def _handle_websocket(
        self,
        websocket: WebSocket,
        session_id: str,
    ) -> None:
        """Accept a WebSocket connection and relay incoming messages."""
        await websocket.accept()
        self._clients[session_id] = websocket
        logger.info("WebUI client connected: session=%s", session_id)

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    data = {"text": raw}

                text = data.get("text", "")
                user_id = data.get("user_id", "anonymous")

                user = PlatformUser(
                    platform="webui",
                    platform_user_id=user_id,
                    username=user_id,
                )
                incoming = IncomingMessage(
                    platform="webui",
                    channel_id=session_id,
                    message_id=str(uuid.uuid4()),
                    user=user,
                    text=text,
                    raw=data,
                )
                await self._dispatch_message(incoming)

        except WebSocketDisconnect:
            logger.info("WebUI client disconnected: session=%s", session_id)
        except Exception:
            logger.exception("WebUI WebSocket error for session=%s", session_id)
        finally:
            self._clients.pop(session_id, None)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the FastAPI / uvicorn server in a background task."""
        logger.info(
            "Starting WebUI adapter on %s:%s...", self._host, self._port
        )
        self._start_queue_consumer()
        self._server_task = asyncio.create_task(self._run_server())
        logger.info("WebUI adapter started")

    async def _run_server(self) -> None:
        """Background task that runs the uvicorn server."""
        config = uvicorn.Config(
            app=self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        try:
            await server.serve()
        except asyncio.CancelledError:
            logger.info("WebUI server task cancelled")
        except Exception:
            logger.exception("WebUI server task crashed")

    async def stop(self) -> None:
        """Disconnect all WebSocket clients and stop the server."""
        logger.info("Stopping WebUI adapter...")
        self._stop_queue_consumer()

        # Close all active WebSocket connections
        for session_id, ws in list(self._clients.items()):
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()

        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

        logger.info("WebUI adapter stopped")

    # ── send_message ──────────────────────────────────────────────

    async def send_message(
        self,
        channel_id: str,
        message: OutgoingMessage,
    ) -> str:
        """Send a message to the WebSocket client identified by ``channel_id``.

        ``channel_id`` is the session_id of the connected browser tab.
        Returns a generated message ID string.
        """
        ws = self._get_client(channel_id)
        message_id = str(uuid.uuid4())

        payload: dict[str, Any] = {
            "type": "message",
            "message_id": message_id,
            "text": message.text,
        }
        if message.buttons:
            payload["buttons"] = [
                [{"text": b.text, "callback_data": b.callback_data, "url": b.url} for b in row]
                for row in message.buttons
            ]

        await self._safe_execute(
            ws.send_text(json.dumps(payload)),
            error_msg="Failed to send WebUI message",
        )
        return message_id

    # ── edit_message ──────────────────────────────────────────────

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        message: OutgoingMessage,
    ) -> None:
        """Edit a previously sent WebUI message by ID.

        Sends a ``{type: "edit", message_id: ..., text: ...}`` event to the
        client, which the front-end should use to update the displayed message.
        """
        ws = self._get_client(channel_id)
        payload = {
            "type": "edit",
            "message_id": message_id,
            "text": message.text,
        }
        await self._safe_execute(
            ws.send_text(json.dumps(payload)),
            error_msg="Failed to edit WebUI message",
        )

    # ── delete_message ────────────────────────────────────────────

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> None:
        """Send a ``{type: "delete"}`` event to remove a message client-side."""
        ws = self._get_client(channel_id)
        payload = {"type": "delete", "message_id": message_id}
        await self._safe_execute(
            ws.send_text(json.dumps(payload)),
            error_msg="Failed to delete WebUI message",
        )

    # ── send_file ─────────────────────────────────────────────────

    async def send_file(
        self,
        channel_id: str,
        file: FileAttachment,
        caption: str | None = None,
    ) -> str:
        """Send a file reference to the WebUI client.

        Sends a JSON event with the filename, mime type, and base64-encoded
        content so the browser can offer a download or preview.
        """
        if file.content is None:
            raise PlatformSendError("FileAttachment.content is required for WebUI")

        import base64

        ws = self._get_client(channel_id)
        message_id = str(uuid.uuid4())
        payload = {
            "type": "file",
            "message_id": message_id,
            "filename": file.filename,
            "mime_type": file.mime_type,
            "content_b64": base64.b64encode(file.content).decode("ascii"),
            "caption": caption,
        }
        await self._safe_execute(
            ws.send_text(json.dumps(payload)),
            error_msg="Failed to send WebUI file",
        )
        return message_id

    # ── send_buttons ──────────────────────────────────────────────

    async def send_buttons(
        self,
        channel_id: str,
        text: str,
        buttons: list[list[ButtonAction]],
    ) -> str:
        """Send a message with inline button options to the WebUI client."""
        msg = OutgoingMessage(text=text, buttons=buttons)
        return await self.send_message(channel_id, msg)

    # ── stream_response ───────────────────────────────────────────

    async def stream_response(
        self,
        channel_id: str,
        chunks: AsyncGenerator[StreamChunk, None],
        initial_text: str = "Processing...",
    ) -> str:
        """Stream a response to the browser, sending each chunk as it arrives.

        Chunk protocol (JSON sent over WebSocket):

        * ``{type: "chunk", message_id: "...", text: "..."}`` — incremental text
        * ``{type: "done",  message_id: "...", text: "..."}`` — final complete text

        The browser should accumulate ``chunk`` deltas and replace the message
        content on ``done``.
        """
        ws = self._get_client(channel_id)
        message_id = str(uuid.uuid4())

        # Send the "typing started" event
        await self._safe_execute(
            ws.send_text(
                json.dumps(
                    {
                        "type": "stream_start",
                        "message_id": message_id,
                        "text": initial_text,
                    }
                )
            ),
            error_msg="Failed to start WebUI stream",
        )

        buffer: list[str] = []
        last_flush = time.monotonic()

        async for chunk in chunks:
            if chunk.is_final:
                if chunk.text:
                    buffer.append(chunk.text)
                break

            if chunk.text:
                buffer.append(chunk.text)

            now = time.monotonic()
            if now - last_flush >= _STREAM_EDIT_INTERVAL and buffer:
                try:
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "chunk",
                                "message_id": message_id,
                                "text": "".join(buffer),
                            }
                        )
                    )
                except Exception:
                    logger.debug("WebUI chunk send failed, client may have disconnected")
                last_flush = now

        # Final "done" event with complete text
        full_text = "".join(buffer)
        try:
            await ws.send_text(
                json.dumps(
                    {
                        "type": "done",
                        "message_id": message_id,
                        "text": full_text,
                    }
                )
            )
        except Exception:
            logger.warning("WebUI final stream 'done' send failed")

        return message_id

    # ── get_user_info ─────────────────────────────────────────────

    async def get_user_info(self, platform_user_id: str) -> PlatformUser:
        """Return a minimal PlatformUser for a WebUI session user."""
        return PlatformUser(
            platform="webui",
            platform_user_id=platform_user_id,
            username=platform_user_id,
        )

    # ── Internal helpers ──────────────────────────────────────────

    def _get_client(self, channel_id: str) -> WebSocket:
        """Return the WebSocket for a session, raising if not connected."""
        ws = self._clients.get(channel_id)
        if ws is None:
            raise PlatformConnectionError(
                f"No WebUI client connected for session '{channel_id}'"
            )
        return ws
