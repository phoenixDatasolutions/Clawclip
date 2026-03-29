"""Replay exporter — export ExecutionTrace to JSON or standalone HTML."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from clawclip.core.types import ExecutionTrace, TraceStep

logger = logging.getLogger(__name__)


# ── JSON export ──────────────────────────────────────────────────


def _step_to_dict(step: TraceStep) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "timestamp": step.timestamp.isoformat(),
        "component": step.component,
        "action": step.action,
        "input_data": step.input_data,
        "output_data": step.output_data,
        "duration_ms": step.duration_ms,
        "cost_usd": step.cost_usd,
        "error": step.error,
        "children": [_step_to_dict(c) for c in step.children],
    }


async def export_json(trace: ExecutionTrace) -> str:
    """Return the trace serialised as a JSON string."""
    data: dict[str, Any] = {
        "trace_id": trace.trace_id,
        "task_id": trace.task_id,
        "user_id": trace.user_id,
        "started_at": trace.started_at.isoformat(),
        "completed_at": trace.completed_at.isoformat() if trace.completed_at else None,
        "success": trace.success,
        "total_cost_usd": trace.total_cost_usd,
        "total_duration_ms": trace.total_duration_ms,
        "steps": [_step_to_dict(s) for s in trace.steps],
    }
    return json.dumps(data, indent=2, default=str)


async def save_json(trace: ExecutionTrace, path: str) -> None:
    """Write the trace as JSON to *path*."""
    content = await export_json(trace)
    Path(path).write_text(content, encoding="utf-8")
    logger.info("Saved JSON trace to %s", path)


# ── HTML export ──────────────────────────────────────────────────


async def export_html(trace: ExecutionTrace) -> str:
    """Return a self-contained HTML report for the trace."""
    json_data = await export_json(trace)

    steps_html_parts: list[str] = []
    for idx, step in enumerate(trace.steps):
        colour = "#d4edda" if not step.error else "#f8d7da"
        steps_html_parts.append(f"""
        <div class="step" style="background:{colour}" onclick="toggleStep({idx})">
          <div class="step-header">
            <span class="step-num">#{idx + 1}</span>
            <span class="step-component">[{step.component}]</span>
            <span class="step-action">{step.action}</span>
            <span class="step-meta">{step.duration_ms} ms | ${step.cost_usd:.6f}</span>
            {"<span class='step-error'>ERROR</span>" if step.error else ""}
          </div>
          <div class="step-detail" id="step-{idx}" style="display:none">
            <pre>{json.dumps(_step_to_dict(step), indent=2, default=str)}</pre>
          </div>
        </div>""")

    steps_html = "\n".join(steps_html_parts)

    duration_s = trace.total_duration_ms / 1000
    completed = trace.completed_at.isoformat() if trace.completed_at else "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>ClawClip Trace: {trace.trace_id[:8]}</title>
  <style>
    body {{ font-family: monospace; margin: 0; padding: 20px; background: #f5f5f5; color: #333; }}
    h1 {{ font-size: 1.4em; margin-bottom: 4px; }}
    .meta {{ color: #666; font-size: 0.9em; margin-bottom: 16px; }}
    .summary-box {{ background: #fff; border: 1px solid #ddd; border-radius: 4px;
                    padding: 12px; margin-bottom: 20px; }}
    .step {{ border: 1px solid #ccc; border-radius: 4px; margin-bottom: 8px;
             padding: 8px 12px; cursor: pointer; }}
    .step-header {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    .step-num {{ font-weight: bold; color: #555; min-width: 32px; }}
    .step-component {{ color: #0066cc; }}
    .step-action {{ flex: 1; }}
    .step-meta {{ color: #888; font-size: 0.85em; }}
    .step-error {{ color: #c00; font-weight: bold; }}
    .step-detail {{ margin-top: 8px; }}
    pre {{ background: #f0f0f0; padding: 8px; overflow-x: auto; font-size: 0.8em;
           border-radius: 4px; white-space: pre-wrap; word-break: break-all; }}
    .badge-ok {{ color: #155724; background: #d4edda; padding: 2px 8px; border-radius: 3px; }}
    .badge-fail {{ color: #721c24; background: #f8d7da; padding: 2px 8px; border-radius: 3px; }}
  </style>
</head>
<body>
  <h1>ClawClip Execution Trace</h1>
  <div class="meta">Trace ID: {trace.trace_id} | Task: {trace.task_id}</div>

  <div class="summary-box">
    <b>Status:</b>
    <span class="{'badge-ok' if trace.success else 'badge-fail'}">
      {'SUCCESS' if trace.success else 'FAILED'}
    </span>
    &nbsp;&nbsp;
    <b>Steps:</b> {len(trace.steps)} &nbsp;&nbsp;
    <b>Duration:</b> {duration_s:.2f}s &nbsp;&nbsp;
    <b>Cost:</b> ${trace.total_cost_usd:.6f}<br>
    <b>Started:</b> {trace.started_at.isoformat()} &nbsp;&nbsp;
    <b>Completed:</b> {completed}
  </div>

  <div id="steps">
    {steps_html}
  </div>

  <script>
    function toggleStep(idx) {{
      var el = document.getElementById('step-' + idx);
      el.style.display = el.style.display === 'none' ? 'block' : 'none';
    }}
    // Embed raw JSON for programmatic access
    window.__clawclip_trace__ = {json_data};
  </script>
</body>
</html>"""
    return html


async def save_html(trace: ExecutionTrace, path: str) -> None:
    """Write the trace as a standalone HTML file to *path*."""
    content = await export_html(trace)
    Path(path).write_text(content, encoding="utf-8")
    logger.info("Saved HTML trace to %s", path)
