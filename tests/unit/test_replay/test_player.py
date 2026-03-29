"""Unit tests for clawclip.replay.player.ReplayPlayer."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clawclip.core.types import ExecutionTrace, TraceStep
from clawclip.replay.player import ReplayPlayer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_trace(n_steps: int = 5) -> ExecutionTrace:
    """Build an ExecutionTrace with *n_steps* synthetic TraceSteps."""
    trace = ExecutionTrace(task_id="test-task", user_id="user-1")
    for i in range(n_steps):
        trace.steps.append(
            TraceStep(
                component="agent" if i % 2 == 0 else "llm",
                action=f"step_{i}",
                input_data={"index": i},
                output_data={"result": f"out_{i}"},
                duration_ms=10 * (i + 1),
                cost_usd=0.001 * (i + 1),
                timestamp=_utcnow(),
            )
        )
    return trace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def trace5():
    """Trace with 5 steps (indices 0-4)."""
    return _make_trace(5)


@pytest.fixture
def player5(trace5):
    return ReplayPlayer(trace5)


# ---------------------------------------------------------------------------
# Navigation tests
# ---------------------------------------------------------------------------


class TestNext:
    def test_next_returns_first_step(self, player5: ReplayPlayer):
        """First call to next() must return step 0."""
        step = player5.next()
        assert step is not None
        assert step.action == "step_0"
        assert player5.current_step == 0

    def test_next_advances(self, player5: ReplayPlayer):
        """Successive next() calls must advance the cursor."""
        s0 = player5.next()
        s1 = player5.next()
        assert s0 is not None
        assert s1 is not None
        assert s0.action == "step_0"
        assert s1.action == "step_1"
        assert player5.current_step == 1

    def test_next_all_steps(self, player5: ReplayPlayer):
        """next() called total_steps times must traverse all steps in order."""
        steps = []
        while True:
            s = player5.next()
            if s is None:
                break
            steps.append(s)
        assert len(steps) == 5
        for i, s in enumerate(steps):
            assert s.action == f"step_{i}"

    def test_next_at_end_returns_none(self, player5: ReplayPlayer):
        """next() when already at the last step must return None."""
        for _ in range(5):
            player5.next()
        result = player5.next()
        assert result is None


class TestPrev:
    def test_prev_goes_back(self, player5: ReplayPlayer):
        """next() twice, then prev() must return step 0."""
        player5.next()  # step 0
        player5.next()  # step 1
        step = player5.prev()
        assert step is not None
        assert step.action == "step_0"
        assert player5.current_step == 0

    def test_prev_at_start_returns_none(self, player5: ReplayPlayer):
        """prev() before any next() call must return None."""
        result = player5.prev()
        assert result is None

    def test_prev_after_first_step_returns_none(self, player5: ReplayPlayer):
        """prev() when cursor is at step 0 must return None."""
        player5.next()  # cursor at 0
        result = player5.prev()
        assert result is None

    def test_prev_advances_backward(self, player5: ReplayPlayer):
        """Multiple prev() calls must walk backwards correctly."""
        for _ in range(4):
            player5.next()  # cursor at 3 after this
        player5.prev()  # cursor at 2
        player5.prev()  # cursor at 1
        step = player5.prev()  # cursor at 0
        assert step is not None
        assert step.action == "step_0"


class TestGoto:
    def test_goto(self, player5: ReplayPlayer):
        """goto(2) must jump directly to step 2 and return it."""
        step = player5.goto(2)
        assert step is not None
        assert step.action == "step_2"
        assert player5.current_step == 2

    def test_goto_first(self, player5: ReplayPlayer):
        """goto(0) must jump to the first step."""
        player5.goto(4)  # jump ahead first
        step = player5.goto(0)
        assert step is not None
        assert step.action == "step_0"
        assert player5.current_step == 0

    def test_goto_last(self, player5: ReplayPlayer):
        """goto(total_steps-1) must jump to the last step."""
        step = player5.goto(4)
        assert step is not None
        assert step.action == "step_4"
        assert player5.current_step == 4

    def test_goto_out_of_range_returns_none(self, player5: ReplayPlayer):
        """goto() with an out-of-range index must return None."""
        result = player5.goto(99)
        assert result is None

    def test_goto_negative_returns_none(self, player5: ReplayPlayer):
        """goto(-1) must return None."""
        result = player5.goto(-1)
        assert result is None


class TestReset:
    def test_reset(self, player5: ReplayPlayer):
        """After goto(4), reset() must set current_step to -1."""
        player5.goto(4)
        player5.reset()
        assert player5.current_step == -1

    def test_reset_allows_replay(self, player5: ReplayPlayer):
        """After reset(), next() must return step 0 again."""
        for _ in range(5):
            player5.next()
        player5.reset()
        step = player5.next()
        assert step is not None
        assert step.action == "step_0"

    def test_reset_from_start_is_safe(self, player5: ReplayPlayer):
        """reset() when at -1 must be a safe no-op."""
        player5.reset()
        assert player5.current_step == -1


class TestEdgeCases:
    def test_empty_trace_next_returns_none(self):
        """next() on a trace with no steps must return None immediately."""
        trace = ExecutionTrace(task_id="empty")
        player = ReplayPlayer(trace)
        assert player.next() is None

    def test_empty_trace_goto_returns_none(self):
        """goto(0) on empty trace must return None."""
        trace = ExecutionTrace(task_id="empty")
        player = ReplayPlayer(trace)
        assert player.goto(0) is None

    def test_total_steps_property(self, player5: ReplayPlayer):
        """total_steps must equal the number of steps in the trace."""
        assert player5.total_steps == 5

    def test_initial_current_step(self, player5: ReplayPlayer):
        """Before any navigation, current_step must be -1."""
        assert player5.current_step == -1

    def test_single_step_trace(self):
        """A trace with exactly 1 step must navigate correctly."""
        trace = _make_trace(1)
        player = ReplayPlayer(trace)
        step = player.next()
        assert step is not None
        assert step.action == "step_0"
        # Second next() should return None
        assert player.next() is None
        # prev() from step 0 should return None
        assert player.prev() is None


class TestGetStateAt:
    def test_get_state_at_accumulates_cost(self):
        """get_state_at(n) must accumulate cost_usd from steps 0..n."""
        trace = _make_trace(3)
        player = ReplayPlayer(trace)
        state = player.get_state_at(2)
        # Steps 0,1,2 have cost 0.001, 0.002, 0.003 => total 0.006
        expected = sum(0.001 * (i + 1) for i in range(3))
        assert abs(state["cumulative_cost_usd"] - expected) < 1e-9

    def test_get_state_at_out_of_range(self):
        """get_state_at() with an out-of-range index must return {}."""
        trace = _make_trace(3)
        player = ReplayPlayer(trace)
        assert player.get_state_at(99) == {}
        assert player.get_state_at(-1) == {}

    def test_get_state_at_current_action(self):
        """get_state_at(i) must include current_action from step i."""
        trace = _make_trace(4)
        player = ReplayPlayer(trace)
        state = player.get_state_at(3)
        assert state["current_action"] == "step_3"
