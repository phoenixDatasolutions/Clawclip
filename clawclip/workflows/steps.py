"""Workflow step definitions and async executors for each step type."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from clawclip.core.enums import WorkflowStepType
from clawclip.workflows.context import WorkflowContext

logger = logging.getLogger(__name__)

# Restricted builtins for condition expression evaluation
_SAFE_BUILTINS = {
    "True": True,
    "False": False,
    "None": None,
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
}


@dataclass
class WorkflowStepDef:
    """Definition of a single workflow pipeline step."""

    id: str
    type: WorkflowStepType
    name: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


# ── Individual step executors ───────────────────────────────────────────────


async def execute_llm_call(
    step: WorkflowStepDef,
    ctx: WorkflowContext,
    provider: Any,
) -> Any:
    """Call an LLM with a rendered prompt.

    Config keys:
        prompt (str): Jinja-style template resolved against *ctx*.
        model (str): Model identifier.
        system_prompt (str, optional): System message.
        temperature (float, optional): Sampling temperature.
    """
    cfg = step.config
    prompt = ctx.resolve_template(cfg.get("prompt", ""))
    model = cfg.get("model", "")
    system_prompt = cfg.get("system_prompt")
    temperature = cfg.get("temperature", 0.7)

    logger.debug("Step %s: LLM call model=%s", step.id, model)

    # provider interface: generate(prompt, model, system_prompt, temperature) -> str
    if hasattr(provider, "generate"):
        result = await provider.generate(
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
        )
        return result
    # Fallback: simple complete() or chat() method
    if hasattr(provider, "complete"):
        return await provider.complete(prompt, model=model)
    raise RuntimeError(f"LLM provider {provider!r} has no usable generation method")


async def execute_skill(
    step: WorkflowStepDef,
    ctx: WorkflowContext,
    skill_manager: Any,
) -> Any:
    """Execute a ClawClip skill tool.

    Config keys:
        skill (str): Skill name (informational; routing is by tool name).
        tool (str): Tool name to invoke.
        arguments (dict): Arguments passed to the tool (templates resolved).
    """
    from clawclip.core.types import SkillContext  # noqa: PLC0415

    cfg = step.config
    tool_name: str = cfg.get("tool", "")
    raw_args: dict = cfg.get("arguments", {})

    # Resolve template strings inside argument values
    arguments = {
        k: ctx.resolve_template(v) if isinstance(v, str) else v
        for k, v in raw_args.items()
    }

    logger.debug("Step %s: skill execution tool=%s", step.id, tool_name)

    skill_ctx = SkillContext()
    result = await skill_manager.execute(tool_name, arguments, skill_ctx)
    if not result.success:
        raise RuntimeError(f"Skill tool '{tool_name}' failed: {result.error}")
    return result.output


async def execute_condition(
    step: WorkflowStepDef,
    ctx: WorkflowContext,
) -> bool:
    """Evaluate a Python expression and return True/False.

    Config keys:
        expression (str): Python boolean expression. Variables ``steps``,
        ``variables``, and ``trigger`` are injected as dicts.
    """
    cfg = step.config
    expression = ctx.resolve_template(cfg.get("expression", "False"))

    safe_globals = {**_SAFE_BUILTINS}
    safe_locals = {
        "steps": ctx.step_outputs,
        "variables": ctx.variables,
        "trigger": ctx.trigger_data,
    }

    logger.debug("Step %s: evaluating condition: %r", step.id, expression)
    try:
        result = eval(expression, {"__builtins__": _SAFE_BUILTINS}, safe_locals)  # noqa: S307
        return bool(result)
    except Exception as exc:
        logger.warning("Condition step %s evaluation error: %s", step.id, exc)
        return False


async def execute_parallel(
    step: WorkflowStepDef,
    ctx: WorkflowContext,
    engine: Any,
) -> list[Any]:
    """Execute a list of sub-steps concurrently.

    Config keys:
        steps (list[dict]): Sub-step definitions (same schema as top-level steps).
    """
    from clawclip.workflows.parser import _parse_step  # noqa: PLC0415

    cfg = step.config
    raw_steps = cfg.get("steps", [])
    sub_steps = [_parse_step(s) for s in raw_steps]

    logger.debug("Step %s: running %d parallel sub-steps", step.id, len(sub_steps))

    tasks = [engine._execute_step_def(sub, ctx) for sub in sub_steps]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    outputs: list[Any] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error("Parallel sub-step %d failed: %s", i, r)
            outputs.append(None)
        else:
            outputs.append(r)
    return outputs


async def execute_loop(
    step: WorkflowStepDef,
    ctx: WorkflowContext,
    engine: Any,
) -> list[Any]:
    """Iterate over a collection and execute a sub-step for each item.

    Config keys:
        over (str): Template expression that resolves to an iterable.
        step (dict): Sub-step definition executed for each item.

    For each iteration the ``${{ variables._item }}`` and
    ``${{ variables._index }}`` templates are set on *ctx*.
    """
    from clawclip.workflows.parser import _parse_step  # noqa: PLC0415

    cfg = step.config
    over_template: str = cfg.get("over", "[]")
    sub_step_def = _parse_step(cfg.get("step", {}))

    resolved = ctx.resolve_template(over_template)
    try:
        import ast  # noqa: PLC0415
        collection = ast.literal_eval(resolved)
    except Exception:
        # If it resolves to a step output that is already a list, use it directly
        collection = ctx.step_outputs.get(over_template.strip()) or []

    results: list[Any] = []
    for idx, item in enumerate(collection):
        ctx.variables["_item"] = item
        ctx.variables["_index"] = idx
        result = await engine._execute_step_def(sub_step_def, ctx)
        results.append(result)

    ctx.variables.pop("_item", None)
    ctx.variables.pop("_index", None)
    return results


async def execute_human_approval(
    step: WorkflowStepDef,
    ctx: WorkflowContext,
    approval_wf: Any,
) -> bool:
    """Pause the workflow and wait for human approval.

    Config keys:
        message (str): Message shown to the approver.
        timeout_seconds (int): How long to wait before auto-denying.

    If *approval_wf* is None the step immediately returns True (approved)
    so workflows can run in automated environments without a human-in-the-loop.
    """
    cfg = step.config
    message = ctx.resolve_template(cfg.get("message", "Approval required"))
    timeout = cfg.get("timeout_seconds", 300)

    if approval_wf is None:
        logger.warning(
            "Step %s: no approval workflow configured — auto-approving", step.id
        )
        return True

    logger.info("Step %s: waiting for human approval: %s", step.id, message)
    try:
        approved: bool = await asyncio.wait_for(
            approval_wf(message=message, context=ctx),
            timeout=float(timeout),
        )
        return approved
    except asyncio.TimeoutError:
        logger.warning("Step %s: approval timed out after %ss", step.id, timeout)
        return False


# ── Dispatcher ─────────────────────────────────────────────────────────────


async def execute_step(
    step: WorkflowStepDef,
    ctx: WorkflowContext,
    **resources: Any,
) -> Any:
    """Dispatch *step* to the correct executor based on its type.

    Keyword resources consumed by executors:
        provider        — LLM provider (for LLM_CALL)
        skill_manager   — SkillManager (for SKILL_EXEC)
        engine          — WorkflowEngine (for PARALLEL / LOOP)
        approval_wf     — approval coroutine (for HUMAN_APPROVAL)
    """
    step_type = step.type

    if step_type == WorkflowStepType.LLM_CALL:
        return await execute_llm_call(step, ctx, resources["provider"])

    if step_type in (WorkflowStepType.SKILL_EXEC, "skill"):
        return await execute_skill(step, ctx, resources["skill_manager"])

    if step_type == WorkflowStepType.CONDITION:
        return await execute_condition(step, ctx)

    if step_type == WorkflowStepType.PARALLEL:
        return await execute_parallel(step, ctx, resources["engine"])

    if step_type == WorkflowStepType.LOOP:
        return await execute_loop(step, ctx, resources["engine"])

    if step_type == WorkflowStepType.HUMAN_APPROVAL:
        return await execute_human_approval(step, ctx, resources.get("approval_wf"))

    raise ValueError(f"Unsupported workflow step type: {step_type!r}")
