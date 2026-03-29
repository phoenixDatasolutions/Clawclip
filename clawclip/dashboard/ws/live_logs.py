"""WebSocket endpoint and in-memory buffer for live log streaming."""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# ── Log Buffer ────────────────────────────────────────────────────


class LogBuffer:
    """Thread-safe circular buffer that stores the last *maxlen* log lines.

    Used by DashboardLogHandler to persist recent log output for the
    /api/system/logs REST endpoint and the live-log WebSocket.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self._buf: collections.deque[str] = collections.deque(maxlen=maxlen)
        self._lock = threading.Lock()
        # Async queue used to notify WebSocket consumers
        self._queues: list[asyncio.Queue[str]] = []
        self._queues_lock = threading.Lock()

    def add(self, line: str) -> None:
        """Append *line* to the buffer and push to all active WS queues."""
        with self._lock:
            self._buf.append(line)
        # Non-blocking push to each registered async queue
        with self._queues_lock:
            for q in list(self._queues):
                try:
                    q.put_nowait(line)
                except asyncio.QueueFull:
                    pass  # Slow consumer — skip

    def get_recent(self, n: int = 100) -> list[str]:
        """Return the last *n* lines from the buffer (oldest first)."""
        with self._lock:
            lines = list(self._buf)
        return lines[-n:]

    def _register_queue(self, q: asyncio.Queue[str]) -> None:
        with self._queues_lock:
            self._queues.append(q)

    def _unregister_queue(self, q: asyncio.Queue[str]) -> None:
        with self._queues_lock:
            try:
                self._queues.remove(q)
            except ValueError:
                pass


# Module-level singleton — imported by system.py for /api/system/logs
_log_buffer = LogBuffer(maxlen=1000)


# ── Logging Handler ───────────────────────────────────────────────


class DashboardLogHandler(logging.Handler):
    """Logging handler that writes formatted records to the LogBuffer.

    Install once at application start::

        handler = DashboardLogHandler()
        logging.getLogger().addHandler(handler)
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            _log_buffer.add(line)
        except Exception:
            self.handleError(record)


# ── WebSocket Handler ─────────────────────────────────────────────


async def websocket_logs(websocket: WebSocket) -> None:
    """Stream live log lines to a connected WebSocket client.

    On connect, sends the last 100 buffered lines as a batch, then
    streams new lines in real-time as they are logged.

    Message format::

        {"type": "batch", "lines": [...]}          # initial history
        {"type": "line", "text": "...", "ts": "…"} # live updates

    Args:
        websocket: The connected WebSocket instance.
    """
    await websocket.accept()
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=512)
    _log_buffer._register_queue(queue)

    try:
        # Send recent history first
        history = _log_buffer.get_recent(100)
        await websocket.send_text(json.dumps({"type": "batch", "lines": history}))

        while True:
            try:
                line = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "line",
                            "text": line,
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except (WebSocketDisconnect, RuntimeError) as exc:
        logger.info("Log WS client disconnected: %s", exc)
    except Exception:
        logger.exception("Unexpected error in log WebSocket handler")
    finally:
        _log_buffer._unregister_queue(queue)
        logger.debug("Log WS queue unregistered")
