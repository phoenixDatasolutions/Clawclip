"""Unit tests for nexusai.workflows.context — WorkflowContext template engine."""

from __future__ import annotations

import pytest

from nexusai.workflows.context import WorkflowContext


def _ctx(**kwargs) -> WorkflowContext:
    return WorkflowContext(workflow_id="wf1", run_id="run1", **kwargs)


@pytest.mark.unit
class TestWorkflowContext:

    def test_set_and_get_output(self) -> None:
        """set_output/get_output round-trips the value."""
        ctx = _ctx()
        ctx.set_output("step1", "result-value")
        assert ctx.get_output("step1") == "result-value"

    def test_template_step_output(self) -> None:
        """${{ steps.step1.output }} resolves to the stored step output."""
        ctx = _ctx()
        ctx.set_output("step1", "hello")
        resolved = ctx.resolve_template("${{ steps.step1.output }}")
        assert resolved == "hello"

    def test_template_variable(self) -> None:
        """${{ variables.name }} resolves to the matching workflow variable."""
        ctx = _ctx(variables={"name": "NexusAI"})
        resolved = ctx.resolve_template("${{ variables.name }}")
        assert resolved == "NexusAI"

    def test_template_trigger_data(self) -> None:
        """${{ trigger.repo }} resolves to the trigger data field."""
        ctx = _ctx(trigger_data={"repo": "nexusai/core"})
        resolved = ctx.resolve_template("${{ trigger.repo }}")
        assert resolved == "nexusai/core"

    def test_unknown_template_preserved(self) -> None:
        """An unresolvable placeholder is kept as-is in the output."""
        ctx = _ctx()
        template = "${{ unknown.key }}"
        assert ctx.resolve_template(template) == template

    def test_nested_template(self) -> None:
        """Multiple placeholders in a single string are all substituted."""
        ctx = _ctx(variables={"env": "prod"})
        ctx.set_output("s1", "42")
        result = ctx.resolve_template("Env: ${{ variables.env }}, count: ${{ steps.s1.output }}")
        assert result == "Env: prod, count: 42"
