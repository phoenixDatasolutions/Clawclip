"""WorkflowContext — execution state for a single workflow run."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowContext:
    """Mutable execution context for a workflow run.

    Holds all variable state, step outputs, and trigger data for a
    single pipeline execution. Step executors read and write through
    this object so later steps can consume earlier steps' results.

    Template syntax supported by :meth:`resolve_template`:

    - ``${{ steps.<step_id>.output }}``   — a previous step's output
    - ``${{ variables.<name> }}``          — a workflow-level variable
    - ``${{ trigger.<field> }}``           — data from the trigger event
    """

    workflow_id: str
    run_id: str
    variables: dict[str, Any] = field(default_factory=dict)
    step_outputs: dict[str, Any] = field(default_factory=dict)
    trigger_data: dict[str, Any] = field(default_factory=dict)

    # ── Step output access ──────────────────────────────────────────

    def set_output(self, step_id: str, output: Any) -> None:
        """Record the output produced by *step_id*."""
        self.step_outputs[step_id] = output

    def get_output(self, step_id: str) -> Any:
        """Retrieve the output of *step_id*, or ``None`` if not yet run."""
        return self.step_outputs.get(step_id)

    # ── Template resolution ─────────────────────────────────────────

    _TEMPLATE_RE = re.compile(r"\$\{\{\s*([^}]+?)\s*\}\}")

    def resolve_template(self, template: str) -> str:
        """Replace ``${{ expr }}`` placeholders in *template*.

        Supported expressions:

        ==========================================  ================================
        ``steps.<step_id>.output``                  :attr:`step_outputs[step_id]`
        ``variables.<name>``                        :attr:`variables[name]`
        ``trigger.<field>``                         :attr:`trigger_data[field]`
        ==========================================  ================================

        Unknown or missing references are left as-is (the placeholder is kept).
        """
        def _replace(match: re.Match) -> str:
            expr = match.group(1).strip()
            parts = expr.split(".")

            if parts[0] == "steps" and len(parts) >= 3 and parts[2] == "output":
                step_id = parts[1]
                val = self.step_outputs.get(step_id)
                return str(val) if val is not None else match.group(0)

            if parts[0] == "variables" and len(parts) >= 2:
                var_name = ".".join(parts[1:])
                val = self.variables.get(var_name)
                return str(val) if val is not None else match.group(0)

            if parts[0] == "trigger" and len(parts) >= 2:
                field_name = ".".join(parts[1:])
                val = self.trigger_data.get(field_name)
                return str(val) if val is not None else match.group(0)

            return match.group(0)

        return self._TEMPLATE_RE.sub(_replace, template)
