"""NexusAI Event System — async publish/subscribe EventBus with typed events."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar
from uuid import uuid4

logger = logging.getLogger(__name__)


# ── Base Event ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Event:
    """Base event class. All events are immutable."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""


# ── Message Events ──────────────────────────────────────────────


@dataclass(frozen=True)
class MessageReceived(Event):
    """A message arrived on any platform."""
    platform: str = ""
    channel_id: str = ""
    user_id: str = ""
    text: str = ""
    attachments: tuple[dict[str, Any], ...] = ()
    thread_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageSent(Event):
    """A message was sent on a platform."""
    platform: str = ""
    channel_id: str = ""
    message_id: str = ""
    text: str = ""


@dataclass(frozen=True)
class ButtonClicked(Event):
    """A user clicked an inline button."""
    platform: str = ""
    channel_id: str = ""
    user_id: str = ""
    callback_data: str = ""
    message_id: str = ""


# ── LLM Events ─────────────────────────────────────────────────


@dataclass(frozen=True)
class LLMRequestStarted(Event):
    """An LLM request was initiated."""
    provider: str = ""
    model: str = ""
    conversation_id: str = ""


@dataclass(frozen=True)
class LLMStreamChunk(Event):
    """A streaming chunk from an LLM."""
    provider: str = ""
    text: str = ""
    conversation_id: str = ""


@dataclass(frozen=True)
class LLMRequestCompleted(Event):
    """An LLM request finished."""
    provider: str = ""
    model: str = ""
    conversation_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0


@dataclass(frozen=True)
class LLMToolCallRequested(Event):
    """An LLM requested a tool call."""
    provider: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    conversation_id: str = ""


# ── Agent Events ────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentSpawned(Event):
    """A new agent instance was created."""
    agent_id: str = ""
    agent_name: str = ""
    agent_type: str = ""
    parent_agent_id: str | None = None


@dataclass(frozen=True)
class AgentTaskStarted(Event):
    """An agent started working on a task."""
    agent_id: str = ""
    task_id: str = ""
    description: str = ""


@dataclass(frozen=True)
class AgentTaskCompleted(Event):
    """An agent finished a task."""
    agent_id: str = ""
    task_id: str = ""
    success: bool = True
    result_summary: str = ""
    cost_usd: float = 0.0
    duration_ms: int = 0


@dataclass(frozen=True)
class AgentDelegated(Event):
    """An agent delegated a sub-task to another agent."""
    from_agent: str = ""
    to_agent: str = ""
    task_description: str = ""


@dataclass(frozen=True)
class AgentStatusChanged(Event):
    """An agent's status changed."""
    agent_id: str = ""
    old_status: str = ""
    new_status: str = ""


# ── Skill Events ───────────────────────────────────────────────


@dataclass(frozen=True)
class SkillExecuted(Event):
    """A skill was executed."""
    skill_name: str = ""
    tool_name: str = ""
    agent_id: str = ""
    user_id: str = ""
    duration_ms: int = 0
    success: bool = True


# ── Security Events ────────────────────────────────────────────


@dataclass(frozen=True)
class ApprovalRequired(Event):
    """A dangerous operation needs user confirmation."""
    operation: str = ""
    details: str = ""
    user_id: str = ""
    platform: str = ""
    channel_id: str = ""
    approval_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class ApprovalResponse(Event):
    """User responded to an approval request."""
    approval_id: str = ""
    approved: bool = False
    user_id: str = ""


@dataclass(frozen=True)
class AuthFailure(Event):
    """An authentication attempt failed."""
    platform: str = ""
    platform_user_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class RateLimitHit(Event):
    """A rate limit was exceeded."""
    user_id: str = ""
    platform: str = ""
    limit_type: str = ""


# ── Workflow Events ─────────────────────────────────────────────


@dataclass(frozen=True)
class WorkflowStarted(Event):
    """A workflow pipeline started."""
    workflow_id: str = ""
    run_id: str = ""
    trigger_type: str = ""


@dataclass(frozen=True)
class WorkflowStepCompleted(Event):
    """A workflow step completed."""
    workflow_id: str = ""
    run_id: str = ""
    step_name: str = ""
    success: bool = True


@dataclass(frozen=True)
class WorkflowCompleted(Event):
    """A workflow pipeline finished."""
    workflow_id: str = ""
    run_id: str = ""
    success: bool = True
    duration_ms: int = 0


# ── Notification Events ────────────────────────────────────────


@dataclass(frozen=True)
class NotificationSent(Event):
    """A notification was dispatched."""
    notification_id: str = ""
    user_id: str = ""
    platforms: tuple[str, ...] = ()
    severity: str = "info"


# ── Config Events ──────────────────────────────────────────────


@dataclass(frozen=True)
class ConfigChanged(Event):
    """Configuration was hot-reloaded."""
    changed_keys: tuple[str, ...] = ()


# ── Event Bus ──────────────────────────────────────────────────


EventHandler = Callable[[Event], Awaitable[None]]
E = TypeVar("E", bound=Event)


class EventBus:
    """Async publish/subscribe event bus with typed subscriptions.

    Features:
    - Subscribe to specific event types or all events
    - Priority-based handler ordering
    - Event history for debugging
    - Safe handler execution (errors don't crash the bus)
    """

    def __init__(self, history_limit: int = 1000) -> None:
        self._handlers: dict[type[Event], list[tuple[int, EventHandler]]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []
        self._event_history: list[Event] = []
        self._history_limit = history_limit

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], Awaitable[None]],
        priority: int = 50,
    ) -> None:
        """Subscribe to a specific event type.

        Args:
            event_type: The event class to listen for.
            handler: Async callable invoked when the event fires.
            priority: Higher priority handlers run first (default 50).
        """
        self._handlers[event_type].append((priority, handler))  # type: ignore[arg-type]
        self._handlers[event_type].sort(key=lambda x: x[0], reverse=True)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events (for logging, metrics, audit, etc.)."""
        self._global_handlers.append(handler)

    def unsubscribe(self, event_type: type[E], handler: EventHandler) -> None:
        """Remove a handler from a specific event type."""
        self._handlers[event_type] = [
            (p, h) for p, h in self._handlers[event_type] if h is not handler
        ]

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers.

        Handlers for the specific event type AND global handlers are called.
        All handlers run concurrently. Exceptions are logged but don't propagate.
        """
        self._event_history.append(event)
        if len(self._event_history) > self._history_limit:
            self._event_history = self._event_history[-self._history_limit :]

        tasks: list[asyncio.Task[None]] = []
        for _, handler in self._handlers.get(type(event), []):
            tasks.append(asyncio.create_task(self._safe_call(handler, event)))
        for handler in self._global_handlers:
            tasks.append(asyncio.create_task(self._safe_call(handler, event)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_call(self, handler: EventHandler, event: Event) -> None:
        """Call a handler safely — log exceptions but don't propagate."""
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "Event handler %s failed for %s",
                getattr(handler, "__name__", handler),
                type(event).__name__,
            )

    def recent_events(
        self,
        event_type: type[E] | None = None,
        limit: int = 50,
    ) -> list[Event]:
        """Get recent events, optionally filtered by type."""
        if event_type:
            return [e for e in reversed(self._event_history) if isinstance(e, event_type)][:limit]
        return list(reversed(self._event_history))[:limit]

    def clear_history(self) -> None:
        """Clear the event history."""
        self._event_history.clear()
