"""WebSocket endpoint for live agent activity streaming."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from clawclip.core.events import (
    AgentStatusChanged,
    AgentTaskCompleted,
    AgentTaskStarted,
    EventBus,
)

logger = logging.getLogger(__name__)


def _serialize(obj: Any) -> Any:
    """Recursively make an object JSON-safe."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


async def websocket_agents(
    websocket: WebSocket,
    event_bus: EventBus,
) -> None:
    """Stream live agent activity events to a WebSocket client.

    Subscribes to AgentTaskStarted, AgentTaskCompleted, and
    AgentStatusChanged events and forwards each as a JSON message.

    Message format::

        {"event": "AgentTaskStarted", "data": {...}, "ts": "<iso>"}

    Args:
        websocket: The connected WebSocket instance.
        event_bus: The application EventBus to subscribe to.
    """
    await websocket.accept()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)

    async def _enqueue(event: Any) -> None:
        try:
            queue.put_nowait(
                {
                    "event": type(event).__name__,
                    "data": _serialize(event),
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
        except asyncio.QueueFull:
            logger.warning("Agent WS queue full — dropping event %s", type(event).__name__)

    event_bus.subscribe(AgentTaskStarted, _enqueue)
    event_bus.subscribe(AgentTaskCompleted, _enqueue)
    event_bus.subscribe(AgentStatusChanged, _enqueue)

    try:
        while True:
            try:
                # Wait for an event with a short timeout so we can detect disconnect
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_text(json.dumps(msg))
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_text(json.dumps({"event": "ping"}))
    except (WebSocketDisconnect, RuntimeError) as exc:
        logger.info("Agent WS client disconnected: %s", exc)
    except Exception:
        logger.exception("Unexpected error in agent WebSocket handler")
    finally:
        event_bus.unsubscribe(AgentTaskStarted, _enqueue)
        event_bus.unsubscribe(AgentTaskCompleted, _enqueue)
        event_bus.unsubscribe(AgentStatusChanged, _enqueue)
        logger.debug("Agent WS subscriptions cleaned up")
