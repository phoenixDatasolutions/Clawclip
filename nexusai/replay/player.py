"""ReplayPlayer — step through an ExecutionTrace interactively."""

from __future__ import annotations

import logging
from typing import Any

from nexusai.core.types import ExecutionTrace, TraceStep

logger = logging.getLogger(__name__)


class ReplayPlayer:
    """Allows step-by-step navigation through a recorded ExecutionTrace.

    Usage::

        player = ReplayPlayer(trace)
        while step := player.next():
            print(step.action)
    """

    def __init__(self, trace: ExecutionTrace) -> None:
        self._trace = trace
        self._cursor: int = -1  # points at the last *returned* step index

    # ── Properties ───────────────────────────────────────────────

    @property
    def total_steps(self) -> int:
        return len(self._trace.steps)

    @property
    def current_step(self) -> int:
        """0-based index of the step most recently returned, or -1 if before start."""
        return self._cursor

    # ── Navigation ───────────────────────────────────────────────

    def next(self) -> TraceStep | None:
        """Advance one step forward and return it, or None if at the end."""
        next_idx = self._cursor + 1
        if next_idx >= self.total_steps:
            return None
        self._cursor = next_idx
        return self._trace.steps[self._cursor]

    def prev(self) -> TraceStep | None:
        """Step backward and return the step, or None if already at the start."""
        prev_idx = self._cursor - 1
        if prev_idx < 0:
            return None
        self._cursor = prev_idx
        return self._trace.steps[self._cursor]

    def goto(self, step_index: int) -> TraceStep | None:
        """Jump directly to *step_index* (0-based).  Returns None if out of range."""
        if step_index < 0 or step_index >= self.total_steps:
            logger.warning(
                "goto(%d) out of range (0..%d)", step_index, self.total_steps - 1
            )
            return None
        self._cursor = step_index
        return self._trace.steps[self._cursor]

    def reset(self) -> None:
        """Rewind to before the first step."""
        self._cursor = -1

    # ── State reconstruction ──────────────────────────────────────

    def get_state_at(self, step_index: int) -> dict[str, Any]:
        """Return a reconstructed state dict accumulated up to *step_index*.

        The state merges ``output_data`` of every step up to and including
        *step_index*, then overlays a summary of the step itself.
        """
        if step_index < 0 or step_index >= self.total_steps:
            return {}

        accumulated: dict[str, Any] = {
            "trace_id": self._trace.trace_id,
            "task_id": self._trace.task_id,
            "step_index": step_index,
            "total_steps": self.total_steps,
            "cumulative_cost_usd": 0.0,
            "cumulative_duration_ms": 0,
            "components_seen": [],
            "last_error": None,
        }

        for idx, step in enumerate(self._trace.steps[: step_index + 1]):
            accumulated["cumulative_cost_usd"] += step.cost_usd
            accumulated["cumulative_duration_ms"] += step.duration_ms
            if step.component not in accumulated["components_seen"]:
                accumulated["components_seen"].append(step.component)
            if step.error:
                accumulated["last_error"] = step.error
            # Merge output data from each step (later steps win on key collision)
            accumulated.update(step.output_data)

        # Surface the current step explicitly
        current = self._trace.steps[step_index]
        accumulated["current_action"] = current.action
        accumulated["current_component"] = current.component
        return accumulated
