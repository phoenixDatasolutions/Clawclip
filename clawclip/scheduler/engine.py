"""ClawClip Scheduler — APScheduler-based async execution engine."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from clawclip.scheduler.jobs import JobType, ScheduledJob
from clawclip.scheduler.store import JobStore

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    _APSCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _APSCHEDULER_AVAILABLE = False
    AsyncIOScheduler = None  # type: ignore[assignment,misc]
    CronTrigger = None  # type: ignore[assignment]


class SchedulerEngine:
    """Wraps APScheduler's AsyncIOScheduler with ClawClip job management.

    Engines reference optional *agent_engine*, *workflow_engine*, and
    *skill_manager* — any of these may be None if the module is unused.
    """

    def __init__(
        self,
        job_store: JobStore,
        agent_engine: Any = None,
        workflow_engine: Any = None,
        skill_manager: Any = None,
    ) -> None:
        self._store = job_store
        self._agent_engine = agent_engine
        self._workflow_engine = workflow_engine
        self._skill_manager = skill_manager

        if _APSCHEDULER_AVAILABLE:
            self._scheduler: AsyncIOScheduler = AsyncIOScheduler()
        else:
            self._scheduler = None  # type: ignore[assignment]
            logger.warning(
                "apscheduler is not installed — SchedulerEngine will not run jobs. "
                "Install it with: pip install apscheduler>=3.10"
            )

    # ── lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Load persisted jobs and start the underlying APScheduler."""
        jobs = await self._store.list_jobs()
        for job in jobs:
            if job.enabled:
                self._schedule_job(job)

        if self._scheduler is not None:
            self._scheduler.start()
            logger.info("SchedulerEngine started with %d enabled job(s).", sum(1 for j in jobs if j.enabled))

    async def stop(self) -> None:
        """Stop APScheduler gracefully."""
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("SchedulerEngine stopped.")

    # ── job management ────────────────────────────────────────────

    async def add_job(self, job: ScheduledJob) -> None:
        """Persist *job* and schedule it if enabled."""
        await self._store.save_job(job)
        if job.enabled:
            self._schedule_job(job)
        logger.info("Job added: %s (%s) cron=%s", job.name, job.id, job.cron)

    async def remove_job(self, job_id: str) -> None:
        """Remove a job from the store and cancel any scheduled run."""
        await self._store.delete_job(job_id)
        self._unschedule_job(job_id)
        logger.info("Job removed: %s", job_id)

    async def enable_job(self, job_id: str) -> None:
        """Enable a previously disabled job."""
        job = await self._store.get_job(job_id)
        if job is None:
            logger.warning("enable_job: job %s not found", job_id)
            return
        job.enabled = True
        await self._store.update_job(job)
        self._schedule_job(job)
        logger.info("Job enabled: %s", job_id)

    async def disable_job(self, job_id: str) -> None:
        """Disable a job without deleting it from the store."""
        job = await self._store.get_job(job_id)
        if job is None:
            logger.warning("disable_job: job %s not found", job_id)
            return
        job.enabled = False
        await self._store.update_job(job)
        self._unschedule_job(job_id)
        logger.info("Job disabled: %s", job_id)

    async def list_jobs(self) -> list[ScheduledJob]:
        """Return all persisted jobs (enabled and disabled)."""
        return await self._store.list_jobs()

    # ── internal helpers ──────────────────────────────────────────

    def _apscheduler_job_id(self, job_id: str) -> str:
        return f"clawclip_{job_id}"

    def _schedule_job(self, job: ScheduledJob) -> None:
        """Register *job* with APScheduler using its cron expression."""
        if self._scheduler is None:
            return

        aps_id = self._apscheduler_job_id(job.id)

        # Remove existing registration first (idempotent re-schedule).
        if self._scheduler.get_job(aps_id):
            self._scheduler.remove_job(aps_id)

        try:
            parts = job.cron.split()
            if len(parts) == 5:
                minute, hour, day, month, day_of_week = parts
            else:
                raise ValueError(f"Invalid cron expression: {job.cron!r}")

            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
            )
            self._scheduler.add_job(
                self._execute_job,
                trigger=trigger,
                id=aps_id,
                args=[job],
                name=job.name,
                replace_existing=True,
            )
        except Exception as exc:
            logger.error("Failed to schedule job %s (%s): %s", job.name, job.id, exc)

    def _unschedule_job(self, job_id: str) -> None:
        """Remove a job from APScheduler if it is currently scheduled."""
        if self._scheduler is None:
            return
        aps_id = self._apscheduler_job_id(job_id)
        try:
            if self._scheduler.get_job(aps_id):
                self._scheduler.remove_job(aps_id)
        except Exception as exc:
            logger.warning("Could not unschedule job %s: %s", job_id, exc)

    async def _execute_job(self, job: ScheduledJob) -> None:
        """Dispatch *job* to the appropriate engine/manager based on job_type."""
        logger.info("Executing scheduled job: %s (%s)", job.name, job.id)
        job.last_run = datetime.now(timezone.utc)

        try:
            if job.job_type == JobType.AGENT_TASK:
                await self._run_agent_task(job)
            elif job.job_type == JobType.WORKFLOW:
                await self._run_workflow(job)
            elif job.job_type == JobType.SKILL:
                await self._run_skill(job)
            else:
                logger.warning("Unknown job type %s for job %s", job.job_type, job.id)
        except Exception as exc:
            logger.exception(
                "Scheduled job %s (%s) raised an unexpected error: %s",
                job.name,
                job.id,
                exc,
            )
        finally:
            # Persist updated last_run timestamp regardless of outcome.
            await self._store.update_job(job)

    async def _run_agent_task(self, job: ScheduledJob) -> None:
        if self._agent_engine is None:
            logger.warning("agent_engine not configured — skipping job %s", job.id)
            return
        from clawclip.core.types import TaskRequest

        task = TaskRequest(
            description=job.config.get("task_description", ""),
            context={"scheduled_job_id": job.id, "scheduled_job_name": job.name},
        )
        result = await self._agent_engine.run(task)
        logger.info(
            "Agent task job %s finished — success=%s", job.name, getattr(result, "success", "?")
        )

    async def _run_workflow(self, job: ScheduledJob) -> None:
        if self._workflow_engine is None:
            logger.warning("workflow_engine not configured — skipping job %s", job.id)
            return
        workflow_id = job.config.get("workflow_id", "")
        result = await self._workflow_engine.run(workflow_id)
        logger.info(
            "Workflow job %s (workflow_id=%s) finished — success=%s",
            job.name,
            workflow_id,
            getattr(result, "success", "?"),
        )

    async def _run_skill(self, job: ScheduledJob) -> None:
        if self._skill_manager is None:
            logger.warning("skill_manager not configured — skipping job %s", job.id)
            return
        from clawclip.core.types import SkillContext

        skill_name = job.config.get("skill", "")
        tool_name = job.config.get("tool", "")
        arguments = job.config.get("arguments", {})
        ctx = SkillContext(
            config={"scheduled_job_id": job.id},
        )
        result = await self._skill_manager.execute(skill_name, tool_name, arguments, ctx)
        logger.info(
            "Skill job %s (%s.%s) finished — success=%s",
            job.name,
            skill_name,
            tool_name,
            getattr(result, "success", "?"),
        )
