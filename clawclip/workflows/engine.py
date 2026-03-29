"""Workflow Engine — loads and executes YAML-defined multi-step pipelines."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from clawclip.core.types import WorkflowDefinition, WorkflowStep
from clawclip.workflows.context import WorkflowContext
from clawclip.workflows.parser import parse_workflow_file, validate_workflow
from clawclip.workflows.steps import WorkflowStepDef, execute_step

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Executes YAML workflow pipelines respecting step dependencies.

    Features:
    - Topological ordering of steps (``depends_on``)
    - Parallel execution of independent steps via ``asyncio.gather``
    - Progress callback after each step completes
    - Returns a structured result dict with per-step outputs and timing

    Usage::

        engine = WorkflowEngine(skill_manager, llm_provider, trigger_manager)
        await engine.load_workflows("/path/to/workflows/")
        result = await engine.execute_workflow("pr_review", trigger_data={...})
    """

    def __init__(
        self,
        skill_manager: Any,
        llm_provider: Any,
        trigger_manager: Any,
        approval_workflow: Any = None,
    ) -> None:
        self._skill_manager = skill_manager
        self._llm_provider = llm_provider
        self._trigger_manager = trigger_manager
        self._approval_workflow = approval_workflow
        self._workflows: dict[str, WorkflowDefinition] = {}
        self.on_step_complete: Callable[[str, str, Any], None] | None = None

    # ── Loading ─────────────────────────────────────────────────────

    async def load_workflows(self, config_dir: str) -> None:
        """Scan *config_dir* for ``*.yaml`` / ``*.yml`` files and load them.

        Invalid workflow files are logged and skipped.
        """
        root = Path(config_dir)
        if not root.is_dir():
            logger.warning("Workflow config_dir does not exist: %s", config_dir)
            return

        loaded = 0
        for yaml_path in sorted(root.glob("**/*.y*ml")):
            try:
                wf = parse_workflow_file(str(yaml_path))
                errors = validate_workflow(wf)
                if errors:
                    logger.error(
                        "Workflow %s has validation errors: %s", yaml_path, errors
                    )
                    continue
                self.register_workflow(wf)
                loaded += 1
            except Exception as exc:
                logger.error("Failed to load workflow %s: %s", yaml_path, exc)

        logger.info("Loaded %d workflow(s) from %s", loaded, config_dir)

    def register_workflow(self, wf: WorkflowDefinition) -> None:
        """Register a parsed workflow and set up its trigger."""
        self._workflows[wf.workflow_id] = wf
        self._setup_trigger(wf)
        logger.debug("Registered workflow: %s", wf.workflow_id)

    # ── Execution ───────────────────────────────────────────────────

    async def execute_workflow(
        self,
        workflow_id: str,
        trigger_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a registered workflow by ID.

        Args:
            workflow_id: The workflow to run.
            trigger_data: Data passed from the trigger event.

        Returns:
            A dict::

                {
                    "status": "completed" | "failed",
                    "outputs": {step_id: result, ...},
                    "duration_ms": int,
                    "error": str | None,
                }
        """
        wf = self._workflows.get(workflow_id)
        if not wf:
            return {
                "status": "failed",
                "outputs": {},
                "duration_ms": 0,
                "error": f"Workflow '{workflow_id}' not registered",
            }

        run_id = str(uuid4())
        ctx = WorkflowContext(
            workflow_id=workflow_id,
            run_id=run_id,
            variables=dict(wf.variables),
            trigger_data=trigger_data or {},
        )

        logger.info("Starting workflow '%s' run=%s", workflow_id, run_id)
        start_ms = time.monotonic()

        try:
            await self._run_steps(wf.steps, ctx)
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            return {
                "status": "completed",
                "outputs": dict(ctx.step_outputs),
                "duration_ms": duration_ms,
                "error": None,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            logger.exception("Workflow '%s' failed: %s", workflow_id, exc)
            return {
                "status": "failed",
                "outputs": dict(ctx.step_outputs),
                "duration_ms": duration_ms,
                "error": str(exc),
            }

    # ── Topological execution ────────────────────────────────────────

    async def _run_steps(
        self,
        steps: list[WorkflowStep],
        ctx: WorkflowContext,
    ) -> None:
        """Execute *steps* in dependency-topological order.

        Independent steps (same dependency level) run in parallel.
        """
        step_defs = [self._workflow_step_to_def(s) for s in steps]
        remaining = list(step_defs)
        completed: set[str] = set()

        while remaining:
            # Collect steps whose dependencies are all satisfied
            ready = [
                s for s in remaining
                if all(dep in completed for dep in s.depends_on)
            ]
            if not ready:
                stuck = [s.id for s in remaining]
                raise RuntimeError(
                    f"Workflow deadlock: steps with unresolvable deps: {stuck}"
                )

            # Run ready steps in parallel
            await asyncio.gather(*[self._execute_step_def(s, ctx) for s in ready])

            for s in ready:
                completed.add(s.id)
                remaining.remove(s)

    async def _execute_step_def(
        self,
        step: WorkflowStepDef,
        ctx: WorkflowContext,
    ) -> Any:
        """Execute a single step, record its output, call the progress callback."""
        logger.debug("Executing step '%s' (%s)", step.id, step.type)
        result = await execute_step(
            step,
            ctx,
            provider=self._llm_provider,
            skill_manager=self._skill_manager,
            engine=self,
            approval_wf=self._approval_workflow,
        )
        ctx.set_output(step.id, result)

        if self.on_step_complete is not None:
            try:
                self.on_step_complete(ctx.workflow_id, step.id, result)
            except Exception:
                logger.debug("on_step_complete callback raised", exc_info=True)

        return result

    # ── Trigger wiring ───────────────────────────────────────────────

    def _setup_trigger(self, wf: WorkflowDefinition) -> None:
        """Register the workflow's trigger with the TriggerManager."""
        if self._trigger_manager is None:
            return

        trigger = wf.trigger
        if not trigger:
            return

        raw_type = trigger.get("type", "")
        config = trigger.get("config", {})

        from clawclip.core.enums import TriggerType  # noqa: PLC0415

        if raw_type == TriggerType.WEBHOOK:
            path = config.get("path", f"/{wf.workflow_id}")
            self._trigger_manager.register_webhook_trigger(wf.workflow_id, path)

        elif raw_type == TriggerType.CRON:
            cron = config.get("cron", "")
            if cron:
                self._trigger_manager.register_cron_trigger(wf.workflow_id, cron)

        elif raw_type == TriggerType.EVENT:
            event_type = config.get("event_type", "")
            if event_type:
                self._trigger_manager.register_event_trigger(wf.workflow_id, event_type)

        # Wire up the trigger callback if not yet set
        if self._trigger_manager.on_trigger is None:
            self._trigger_manager.on_trigger = self.execute_workflow

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _workflow_step_to_def(step: WorkflowStep) -> WorkflowStepDef:
        """Convert a :class:`WorkflowStep` (from types.py) to a :class:`WorkflowStepDef`."""
        from clawclip.core.enums import WorkflowStepType  # noqa: PLC0415

        try:
            step_type = WorkflowStepType(step.step_type)
        except ValueError:
            step_type = step.step_type  # type: ignore[assignment]

        return WorkflowStepDef(
            id=step.step_id,
            type=step_type,
            name=step.name,
            config=dict(step.config),
            depends_on=list(step.depends_on),
        )

    @property
    def workflows(self) -> dict[str, WorkflowDefinition]:
        """Read-only view of registered workflows."""
        return dict(self._workflows)
