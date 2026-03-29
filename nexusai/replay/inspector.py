"""StepInspector — introspect and format a single TraceStep."""

from __future__ import annotations

import logging
from typing import Any

from nexusai.core.types import TraceStep

logger = logging.getLogger(__name__)


class StepInspector:
    """Provides rich introspection of a single :class:`TraceStep`.

    Works for LLM steps (prompt/response), tool-call steps, and skill steps.
    """

    def __init__(self, step: TraceStep) -> None:
        self._step = step

    # ── Core properties ──────────────────────────────────────────

    @property
    def summary(self) -> str:
        parts = [f"[{self._step.component}] {self._step.action}"]
        if self._step.error:
            parts.append(f"ERROR: {self._step.error}")
        else:
            parts.append(f"{self._step.duration_ms}ms ${self._step.cost_usd:.6f}")
        return " | ".join(parts)

    @property
    def duration_ms(self) -> float:
        return float(self._step.duration_ms)

    @property
    def token_count(self) -> int:
        d = self._step.output_data
        return int(
            d.get("total_tokens", 0)
            or (d.get("input_tokens", 0) + d.get("output_tokens", 0))
        )

    @property
    def cost(self) -> float:
        return self._step.cost_usd

    # ── LLM step helpers ─────────────────────────────────────────

    def get_prompt(self) -> str | None:
        """Return the prompt string for LLM steps, or None."""
        if self._step.component != "llm":
            return None
        return self._step.input_data.get("prompt") or self._step.input_data.get("messages")  # type: ignore[return-value]

    def get_response(self) -> str | None:
        """Return the LLM response text, or None."""
        if self._step.component != "llm":
            return None
        return self._step.output_data.get("response") or self._step.output_data.get("content")  # type: ignore[return-value]

    # ── Tool step helper ─────────────────────────────────────────

    def get_tool_call(self) -> dict[str, Any] | None:
        """Return tool-call details for tool steps, or None."""
        if "tool_name" not in self._step.input_data:
            return None
        return {
            "tool_name": self._step.input_data.get("tool_name"),
            "arguments": self._step.input_data.get("arguments", {}),
            "result": self._step.output_data,
        }

    # ── Display ──────────────────────────────────────────────────

    def format_for_display(self) -> str:
        """Return a human-readable multi-line representation of the step."""
        step = self._step
        lines: list[str] = [
            f"Step ID   : {step.step_id}",
            f"Timestamp : {step.timestamp.isoformat()}",
            f"Component : {step.component}",
            f"Action    : {step.action}",
            f"Duration  : {step.duration_ms} ms",
            f"Cost      : ${step.cost_usd:.6f}",
        ]

        if step.error:
            lines.append(f"Error     : {step.error}")

        if step.input_data:
            lines.append("Input:")
            for k, v in step.input_data.items():
                lines.append(f"  {k}: {_truncate(str(v), 120)}")

        if step.output_data:
            lines.append("Output:")
            for k, v in step.output_data.items():
                lines.append(f"  {k}: {_truncate(str(v), 120)}")

        if step.children:
            lines.append(f"Children  : {len(step.children)} sub-step(s)")

        return "\n".join(lines)


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"
