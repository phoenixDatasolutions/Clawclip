"""Unit tests for clawclip.replay.recorder.ExecutionRecorder."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clawclip.core.events import (
    AgentTaskCompleted,
    AgentTaskStarted,
    EventBus,
)
from clawclip.core.types import ExecutionTrace
from clawclip.replay.recorder import ExecutionRecorder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _run_task(
    bus: EventBus,
    task_id: str = "task-1",
    *,
    success: bool = True,
    cost_usd: float = 0.01,
    duration_ms: int = 100,
) -> None:
    """Simulate a complete agent task cycle on the event bus."""
    await bus.publish(
        AgentTaskStarted(
            agent_id="agent-1",
            task_id=task_id,
            description="test task",
            timestamp=_utcnow(),
        )
    )
    await bus.publish(
        AgentTaskCompleted(
            agent_id="agent-1",
            task_id=task_id,
            success=success,
            result_summary="done",
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            timestamp=_utcnow(),
        )
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def recorder():
    bus = EventBus()
    rec = ExecutionRecorder(event_bus=bus, max_traces=100)
    await rec.start()
    yield rec, bus
    await rec.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecorderLifecycle:
    async def test_start_stop(self):
        """start() / stop() must not raise."""
        bus = EventBus()
        rec = ExecutionRecorder(event_bus=bus)
        await rec.start()
        await rec.stop()

    async def test_double_start_is_safe(self):
        """Calling start() twice must not raise or duplicate subscriptions."""
        bus = EventBus()
        rec = ExecutionRecorder(event_bus=bus)
        await rec.start()
        await rec.start()  # second call should be a no-op
        await rec.stop()


class TestRecorderCaptures:
    async def test_recorder_captures_agent_events(self, recorder):
        """Publishing AgentTaskStarted + Completed must create a stored trace."""
        rec, bus = recorder
        await _run_task(bus, task_id="t1")
        trace = await rec.get_trace("t1")
        assert trace is not None
        assert isinstance(trace, ExecutionTrace)

    async def test_trace_success_field(self, recorder):
        """Completed trace must record the success flag from AgentTaskCompleted."""
        rec, bus = recorder
        await _run_task(bus, task_id="t_success", success=True)
        trace = await rec.get_trace("t_success")
        assert trace.success is True

    async def test_trace_failure_field(self, recorder):
        """Completed trace with success=False must reflect that."""
        rec, bus = recorder
        await _run_task(bus, task_id="t_fail", success=False)
        trace = await rec.get_trace("t_fail")
        assert trace.success is False

    async def test_trace_cost_and_duration(self, recorder):
        """Completed trace must store cost_usd and duration_ms from the event."""
        rec, bus = recorder
        await _run_task(bus, task_id="t_cost", cost_usd=1.23, duration_ms=456)
        trace = await rec.get_trace("t_cost")
        assert abs(trace.total_cost_usd - 1.23) < 1e-9
        assert trace.total_duration_ms == 456


class TestGetTrace:
    async def test_get_trace(self, recorder):
        """get_trace(run_id) must return a non-None ExecutionTrace after the run."""
        rec, bus = recorder
        await _run_task(bus, task_id="t2")
        trace = await rec.get_trace("t2")
        assert trace is not None
        assert trace.task_id == "t2"

    async def test_get_trace_missing(self, recorder):
        """get_trace() for an unknown run_id must return None."""
        rec, _ = recorder
        result = await rec.get_trace("does-not-exist")
        assert result is None


class TestListTraces:
    async def test_list_traces(self, recorder):
        """After 3 separate task runs, list_traces() must return 3 items."""
        rec, bus = recorder
        for i in range(3):
            await _run_task(bus, task_id=f"list-task-{i}")
        traces = await rec.list_traces()
        assert len(traces) == 3

    async def test_list_traces_empty(self, recorder):
        """list_traces() with no recorded runs must return []."""
        rec, _ = recorder
        traces = await rec.list_traces()
        assert traces == []

    async def test_list_traces_structure(self, recorder):
        """Each entry in list_traces() must have expected summary keys."""
        rec, bus = recorder
        await _run_task(bus, task_id="struct-task")
        traces = await rec.list_traces()
        entry = traces[0]
        for key in ("trace_id", "task_id", "started_at", "success", "total_cost_usd"):
            assert key in entry, f"Missing key '{key}' in trace summary"

    async def test_list_traces_limit(self, recorder):
        """list_traces(limit=2) must cap results at 2."""
        rec, bus = recorder
        for i in range(5):
            await _run_task(bus, task_id=f"limit-task-{i}")
        traces = await rec.list_traces(limit=2)
        assert len(traces) == 2


class TestLRUEviction:
    async def test_lru_eviction(self):
        """With max_traces=2, recording a 3rd task must evict the oldest trace."""
        bus = EventBus()
        rec = ExecutionRecorder(event_bus=bus, max_traces=2)
        await rec.start()

        await _run_task(bus, task_id="old-1")
        await _run_task(bus, task_id="old-2")
        await _run_task(bus, task_id="new-3")

        # Only 2 should remain
        traces = await rec.list_traces()
        assert len(traces) == 2

        # The oldest task should have been evicted
        ids = {t["task_id"] for t in traces}
        assert "old-1" not in ids
        assert "old-2" in ids or "new-3" in ids

        await rec.stop()

    async def test_lru_eviction_preserves_newest(self):
        """After max+1 tasks, the most-recently completed task must be retained."""
        bus = EventBus()
        rec = ExecutionRecorder(event_bus=bus, max_traces=3)
        await rec.start()

        for i in range(4):
            await _run_task(bus, task_id=f"lru-task-{i}")

        traces = await rec.list_traces()
        assert len(traces) == 3

        ids = {t["task_id"] for t in traces}
        # lru-task-3 is the most recent and must survive
        assert "lru-task-3" in ids

        await rec.stop()


class TestDeleteTrace:
    async def test_delete_trace(self, recorder):
        """delete_trace(run_id) must remove it from subsequent get_trace calls."""
        rec, bus = recorder
        await _run_task(bus, task_id="del-task")
        assert await rec.get_trace("del-task") is not None
        await rec.delete_trace("del-task")
        assert await rec.get_trace("del-task") is None
