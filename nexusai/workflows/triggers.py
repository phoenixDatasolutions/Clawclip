"""Workflow trigger management — webhook, cron, and event-based triggers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from nexusai.core.enums import TriggerType

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False


# Callback type: receives (workflow_id, trigger_data) and fires the workflow
OnTriggerCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class TriggerConfig:
    """Configuration for a single workflow trigger."""

    type: TriggerType
    config: dict[str, Any] = field(default_factory=dict)


class TriggerManager:
    """Manages all trigger registrations and fires workflows on activation.

    Supported trigger types:

    - **webhook** — an HTTP path; external code calls :meth:`fire` directly.
    - **cron**    — schedule via APScheduler (requires ``apscheduler`` package).
    - **event**   — fired when a named platform event occurs.
    """

    def __init__(self) -> None:
        self._webhook_triggers: dict[str, str] = {}   # path  → workflow_id
        self._cron_triggers: dict[str, str] = {}       # workflow_id → cron
        self._event_triggers: dict[str, list[str]] = {}  # event_type → [workflow_id]
        self._scheduler: Any = None
        self.on_trigger: OnTriggerCallback | None = None

    # ── Registration ────────────────────────────────────────────────

    def register_webhook_trigger(self, workflow_id: str, path: str) -> None:
        """Register *workflow_id* to fire when *path* receives a webhook."""
        self._webhook_triggers[path] = workflow_id
        logger.info("Webhook trigger registered: %s → %s", path, workflow_id)

    def register_cron_trigger(self, workflow_id: str, cron: str) -> None:
        """Schedule *workflow_id* to run on a cron expression.

        Requires the ``apscheduler`` package. If unavailable the
        registration is logged as a warning and silently ignored.
        """
        self._cron_triggers[workflow_id] = cron

        if not _APSCHEDULER_AVAILABLE:
            logger.warning(
                "apscheduler not installed — cron trigger for '%s' will not fire",
                workflow_id,
            )
            return

        scheduler = self._get_scheduler()
        minute, hour, day, month, day_of_week = (cron.split() + ["*"] * 5)[:5]
        scheduler.add_job(
            self._cron_fire,
            "cron",
            id=f"cron_{workflow_id}",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            kwargs={"workflow_id": workflow_id},
            replace_existing=True,
        )
        logger.info("Cron trigger registered: %s @ '%s'", workflow_id, cron)

    def register_event_trigger(self, workflow_id: str, event_type: str) -> None:
        """Fire *workflow_id* when *event_type* event is published."""
        self._event_triggers.setdefault(event_type, []).append(workflow_id)
        logger.info("Event trigger registered: %s on event '%s'", workflow_id, event_type)

    # ── Firing ──────────────────────────────────────────────────────

    async def fire(self, workflow_id: str, trigger_data: dict[str, Any]) -> None:
        """Manually fire a workflow with the given trigger data.

        Calls :attr:`on_trigger` if set.
        """
        logger.info("Firing workflow '%s' with trigger_data keys=%s",
                    workflow_id, list(trigger_data.keys()))
        if self.on_trigger is not None:
            await self.on_trigger(workflow_id, trigger_data)
        else:
            logger.warning("TriggerManager.on_trigger not set — workflow '%s' not executed", workflow_id)

    async def fire_webhook(self, path: str, data: dict[str, Any]) -> bool:
        """Fire the workflow registered for *path*.

        Returns True if a matching workflow was found.
        """
        workflow_id = self._webhook_triggers.get(path)
        if not workflow_id:
            return False
        await self.fire(workflow_id, {"path": path, **data})
        return True

    async def fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire all workflows registered for *event_type*."""
        for workflow_id in self._event_triggers.get(event_type, []):
            await self.fire(workflow_id, {"event_type": event_type, **data})

    # ── Scheduler helpers ───────────────────────────────────────────

    def start_scheduler(self) -> None:
        """Start the APScheduler background scheduler."""
        if _APSCHEDULER_AVAILABLE:
            self._get_scheduler().start()
            logger.info("Cron scheduler started")

    def stop_scheduler(self) -> None:
        """Stop the APScheduler background scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            logger.info("Cron scheduler stopped")

    def _get_scheduler(self) -> Any:
        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler()
        return self._scheduler

    async def _cron_fire(self, workflow_id: str) -> None:
        """Called by APScheduler when a cron job fires."""
        await self.fire(workflow_id, {"trigger_type": "cron"})
