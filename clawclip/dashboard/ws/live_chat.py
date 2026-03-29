"""WebSocket endpoint for the live chat interface."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# ── Protocol constants ────────────────────────────────────────────

_MSG_CHUNK = "chunk"
_MSG_DONE = "done"
_MSG_ERROR = "error"


# ── WebSocket Handler ─────────────────────────────────────────────


async def websocket_chat(
    websocket: WebSocket,
    agent_engine: Any,
    event_bus: Any = None,
    default_agent: str = "coordinator",
) -> None:
    """Handle a persistent chat WebSocket connection.

    The client sends JSON frames::

        {"message": "Hello!", "agent": "coordinator", "model": "claude-3-5-sonnet-20241022"}

    The server streams back frames::

        {"type": "chunk",  "text": "partial response…"}
        {"type": "done",   "text": "",  "cost_usd": 0.012, "tokens": 1024}
        {"type": "error",  "text": "error description"}

    An empty ``agent`` or ``model`` value falls back to the engine's default.

    Args:
        websocket: The connected WebSocket instance.
        agent_engine: The AgentEngine (or compatible) instance to execute tasks.
        event_bus: Optional EventBus — unused here but available for future hooks.
        default_agent: Agent type to use when the client omits the ``agent`` field.
    """
    await websocket.accept()
    logger.info("Chat WS client connected")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, _MSG_ERROR, "Invalid JSON payload")
                continue

            message: str = str(payload.get("message", "")).strip()
            if not message:
                await _send(websocket, _MSG_ERROR, "Empty message")
                continue

            agent_type: str = str(payload.get("agent", "") or default_agent)
            model: str | None = payload.get("model") or None

            if agent_engine is None:
                await _send(websocket, _MSG_ERROR, "Agent engine not available")
                continue

            await _run_agent(websocket, agent_engine, message, agent_type, model)

    except (WebSocketDisconnect, RuntimeError) as exc:
        logger.info("Chat WS client disconnected: %s", exc)
    except Exception:
        logger.exception("Unexpected error in chat WebSocket handler")
    finally:
        logger.debug("Chat WS connection closed")


# ── Internal Helpers ──────────────────────────────────────────────


async def _send(websocket: WebSocket, msg_type: str, text: str, **extra: Any) -> None:
    """Send a typed message frame to the client."""
    frame: dict[str, Any] = {"type": msg_type, "text": text, **extra}
    try:
        await websocket.send_text(json.dumps(frame))
    except Exception as exc:
        logger.debug("Failed to send WS frame: %s", exc)
        raise


async def _run_agent(
    websocket: WebSocket,
    agent_engine: Any,
    message: str,
    agent_type: str,
    model: str | None,
) -> None:
    """Execute the agent and stream the response back over *websocket*."""
    from clawclip.core.types import TaskRequest

    task = TaskRequest(description=message)
    # Inject model override if provided and the engine supports it
    if model:
        task.context["preferred_model"] = model

    # Prefer streaming execution if the engine exposes stream_task()
    if hasattr(agent_engine, "stream_task"):
        try:
            async for event in agent_engine.stream_task(task, agent_type=agent_type):
                # AgentStreamEvent: text_delta, tool_use, delegation, status_change, complete, error
                event_type: str = getattr(event, "event_type", "")
                text: str = getattr(event, "text", "") or ""

                if event_type == "text_delta":
                    await _send(websocket, _MSG_CHUNK, text)
                elif event_type == "complete":
                    meta = getattr(event, "metadata", {}) or {}
                    await _send(
                        websocket,
                        _MSG_DONE,
                        text,
                        cost_usd=meta.get("cost_usd", 0.0),
                        tokens=meta.get("total_tokens", 0),
                    )
                    return
                elif event_type == "error":
                    await _send(websocket, _MSG_ERROR, text or "Agent error")
                    return
                # Other event types (tool_use, delegation, status_change) are silently consumed
        except Exception as exc:
            logger.exception("Agent stream error")
            await _send(websocket, _MSG_ERROR, str(exc))
        return

    # Fall back to non-streaming execute_task()
    try:
        result = await asyncio.wait_for(
            agent_engine.execute_task(task, agent_type=agent_type),
            timeout=300.0,
        )
        output: str = getattr(result, "output", str(result))
        cost: float = getattr(result, "cost_usd", 0.0)
        # Stream the whole response as a single chunk then done
        await _send(websocket, _MSG_CHUNK, output)
        await _send(websocket, _MSG_DONE, "", cost_usd=cost, tokens=0)
    except asyncio.TimeoutError:
        await _send(websocket, _MSG_ERROR, "Agent timed out after 300 seconds")
    except Exception as exc:
        logger.exception("Agent execute_task error")
        await _send(websocket, _MSG_ERROR, str(exc))
