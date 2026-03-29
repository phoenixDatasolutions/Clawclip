"""ExecutionRecorder — subscribe to EventBus and capture execution traces."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from nexusai.core.events import (
    AgentTaskCompleted,
    AgentTaskStarted,
    Event,
    EventBus,
    LLMRequestCompleted,
    LLMRequestStarted,
    LLMToolCallRequested,
    SkillExecuted,
)
from nexusai.core.types import ExecutionTrace, TraceStep

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionRecorder:
    """Subscribes to all relevant EventBus events and builds ExecutionTraces.

    Traces are kept in an in-memory LRU dict (keyed by task_id / run_id).
    When *max_traces* is exceeded the oldest entry is evicted.
    """

    def __init__(self, event_bus: EventBus, max_traces: int = 1000) -> None:
        self._event_bus = event_bus
        self._max_traces = max_traces
        # OrderedDict used as LRU cache (oldest first)
        self._traces: OrderedDict[str, ExecutionTrace] = OrderedDict()
        # Pending traces keyed by task_id (started but not yet completed)
        self._pending: dict[str, ExecutionTrace] = {}
        self._running = False

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to agent / LLM / skill events and begin recording."""
        if self._running:
            return
        self._running = True
        self._event_bus.subscribe(AgentTaskStarted, self._on_task_started)
        self._event_bus.subscribe(AgentTaskCompleted, self._on_task_completed)
        self._event_bus.subscribe(LLMRequestStarted, self._on_llm_started)
        self._event_bus.subscribe(LLMRequestCompleted, self._on_llm_completed)
        self._event_bus.subscribe(LLMToolCallRequested, self._on_tool_call)
        self._event_bus.subscribe(SkillExecuted, self._on_skill_executed)
        logger.info("ExecutionRecorder started")

    async def stop(self) -> None:
        """Unsubscribe from all events."""
        if not self._running:
            return
        self._running = False
        self._event_bus.unsubscribe(AgentTaskStarted, self._on_task_started)
        self._event_bus.unsubscribe(AgentTaskCompleted, self._on_task_completed)
        self._event_bus.unsubscribe(LLMRequestStarted, self._on_llm_started)
        self._event_bus.unsubscribe(LLMRequestCompleted, self._on_llm_completed)
        self._event_bus.unsubscribe(LLMToolCallRequested, self._on_tool_call)
        self._event_bus.unsubscribe(SkillExecuted, self._on_skill_executed)
        logger.info("ExecutionRecorder stopped")

    # ── Query ────────────────────────────────────────────────────

    async def get_trace(self, run_id: str) -> ExecutionTrace | None:
        return self._traces.get(run_id)

    async def list_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        traces = list(reversed(list(self._traces.values())))[:limit]
        return [
            {
                "trace_id": t.trace_id,
                "task_id": t.task_id,
                "user_id": t.user_id,
                "started_at": t.started_at.isoformat(),
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "steps": len(t.steps),
                "total_cost_usd": t.total_cost_usd,
                "total_duration_ms": t.total_duration_ms,
                "success": t.success,
            }
            for t in traces
        ]

    async def delete_trace(self, run_id: str) -> None:
        self._traces.pop(run_id, None)
        self._pending.pop(run_id, None)

    # ── Event handlers ───────────────────────────────────────────

    async def _on_task_started(self, event: AgentTaskStarted) -> None:
        trace = ExecutionTrace(
            task_id=event.task_id,
            started_at=event.timestamp,
        )
        self._pending[event.task_id] = trace

    async def _on_task_completed(self, event: AgentTaskCompleted) -> None:
        trace = self._pending.pop(event.task_id, None)
        if trace is None:
            # Received completion without start — create a stub
            trace = ExecutionTrace(task_id=event.task_id)
        trace.completed_at = event.timestamp
        trace.success = event.success
        trace.total_cost_usd = event.cost_usd
        trace.total_duration_ms = event.duration_ms
        self._store_trace(event.task_id, trace)

    async def _on_llm_started(self, event: LLMRequestStarted) -> None:
        step = TraceStep(
            timestamp=event.timestamp,
            component="llm",
            action="request_started",
            input_data={"provider": event.provider, "model": event.model},
        )
        self._append_to_pending(event.source or event.conversation_id, step)

    async def _on_llm_completed(self, event: LLMRequestCompleted) -> None:
        step = TraceStep(
            timestamp=event.timestamp,
            component="llm",
            action="request_completed",
            input_data={"provider": event.provider, "model": event.model},
            output_data={
                "input_tokens": event.input_tokens,
                "output_tokens": event.output_tokens,
            },
            duration_ms=event.duration_ms,
            cost_usd=event.cost_usd,
        )
        self._append_to_pending(event.source or event.conversation_id, step)

    async def _on_tool_call(self, event: LLMToolCallRequested) -> None:
        step = TraceStep(
            timestamp=event.timestamp,
            component="llm",
            action="tool_call_requested",
            input_data={"tool_name": event.tool_name, "arguments": event.arguments},
        )
        self._append_to_pending(event.source or event.conversation_id, step)

    async def _on_skill_executed(self, event: SkillExecuted) -> None:
        step = TraceStep(
            timestamp=event.timestamp,
            component="skill",
            action=f"skill:{event.skill_name}:{event.tool_name}",
            input_data={"agent_id": event.agent_id, "user_id": event.user_id},
            output_data={"success": event.success},
            duration_ms=event.duration_ms,
        )
        self._append_to_pending(event.agent_id or event.source, step)

    # ── Internal ─────────────────────────────────────────────────

    def _append_to_pending(self, key: str, step: TraceStep) -> None:
        """Add *step* to the first pending trace that matches *key* (loose)."""
        # Best effort: attach to any live pending trace
        for trace in self._pending.values():
            trace.steps.append(step)
            return
        # No pending trace — create a transient one
        trace = ExecutionTrace()
        trace.steps.append(step)
        self._pending[key] = trace

    def _store_trace(self, key: str, trace: ExecutionTrace) -> None:
        """Store a completed trace with LRU eviction."""
        if key in self._traces:
            self._traces.move_to_end(key)
        else:
            self._traces[key] = trace
            if len(self._traces) > self._max_traces:
                self._traces.popitem(last=False)
