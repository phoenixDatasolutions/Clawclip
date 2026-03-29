"""Unit tests for clawclip.workflows.steps — individual step executors."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from clawclip.core.enums import WorkflowStepType
from clawclip.core.types import SkillResult
from clawclip.workflows.context import WorkflowContext
from clawclip.workflows.steps import (
    WorkflowStepDef,
    execute_condition,
    execute_llm_call,
    execute_skill,
    execute_step,
)


def _ctx(**kwargs) -> WorkflowContext:
    return WorkflowContext(workflow_id="wf", run_id="r1", **kwargs)


def _step(step_id: str, step_type: WorkflowStepType, config: dict) -> WorkflowStepDef:
    return WorkflowStepDef(id=step_id, type=step_type, config=config)


@pytest.mark.unit
class TestWorkflowSteps:

    async def test_execute_condition_true(self) -> None:
        """Condition step with '1 == 1' evaluates to True."""
        step = _step("c1", WorkflowStepType.CONDITION, {"expression": "1 == 1"})
        result = await execute_condition(step, _ctx())
        assert result is True

    async def test_execute_condition_false(self) -> None:
        """Condition step with '1 == 2' evaluates to False."""
        step = _step("c2", WorkflowStepType.CONDITION, {"expression": "1 == 2"})
        result = await execute_condition(step, _ctx())
        assert result is False

    async def test_execute_skill_step(self) -> None:
        """execute_skill calls skill_manager.execute with correct tool and args."""
        skill_mgr = MagicMock()
        skill_mgr.execute = AsyncMock(return_value=SkillResult(success=True, output="done"))

        step = _step("s1", WorkflowStepType.SKILL_EXEC, {
            "skill": "shell",
            "tool": "execute_bash",
            "arguments": {"command": "echo hi"},
        })
        result = await execute_skill(step, _ctx(), skill_mgr)

        skill_mgr.execute.assert_called_once()
        call_args = skill_mgr.execute.call_args
        assert call_args[0][0] == "execute_bash"
        assert result == "done"

    async def test_execute_llm_call(self) -> None:
        """execute_llm_call passes resolved prompt to provider.generate()."""
        provider = MagicMock()
        provider.generate = AsyncMock(return_value="LLM output")

        step = _step("l1", WorkflowStepType.LLM_CALL, {
            "model": "fake-model",
            "prompt": "Hello world",
        })
        result = await execute_llm_call(step, _ctx(), provider)

        provider.generate.assert_called_once()
        call_kwargs = provider.generate.call_args[1]
        assert call_kwargs.get("prompt") == "Hello world" or provider.generate.call_args[0][0] == "Hello world"

    async def test_execute_parallel_steps(self) -> None:
        """execute_step dispatches CONDITION steps correctly in parallel."""
        ctx = _ctx()
        step_a = _step("a", WorkflowStepType.CONDITION, {"expression": "True"})
        step_b = _step("b", WorkflowStepType.CONDITION, {"expression": "False"})

        results = await asyncio.gather(
            execute_condition(step_a, ctx),
            execute_condition(step_b, ctx),
        )
        assert results == [True, False]

    async def test_template_substitution_in_step(self) -> None:
        """Step config using ${{ variables.x }} is resolved before execution."""
        ctx = _ctx(variables={"cmd": "echo substituted"})
        skill_mgr = MagicMock()
        skill_mgr.execute = AsyncMock(return_value=SkillResult(success=True, output="ok"))

        step = _step("s2", WorkflowStepType.SKILL_EXEC, {
            "skill": "shell",
            "tool": "execute_bash",
            "arguments": {"command": "${{ variables.cmd }}"},
        })
        await execute_skill(step, ctx, skill_mgr)

        call_args = skill_mgr.execute.call_args[0]
        assert call_args[1]["command"] == "echo substituted"
