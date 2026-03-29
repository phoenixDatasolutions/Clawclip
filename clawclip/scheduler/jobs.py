"""ClawClip Scheduler — job definitions and factory helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4


def _uuid() -> str:
    return str(uuid4())


class JobType(str, Enum):
    """Discriminates the payload stored in ScheduledJob.config."""

    AGENT_TASK = "agent_task"
    WORKFLOW = "workflow"
    SKILL = "skill"


@dataclass
class ScheduledJob:
    """A single scheduled job persisted by JobStore and executed by SchedulerEngine."""

    id: str = field(default_factory=_uuid)
    name: str = ""
    job_type: JobType = JobType.AGENT_TASK
    cron: str = "* * * * *"
    config: dict = field(default_factory=dict)
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None


# ── Factory helpers ──────────────────────────────────────────────


def create_agent_job(
    name: str,
    cron: str,
    task_description: str,
    agent_type: str,
    provider: str,
) -> ScheduledJob:
    """Create a ScheduledJob that runs an agent task on a cron schedule."""
    return ScheduledJob(
        name=name,
        job_type=JobType.AGENT_TASK,
        cron=cron,
        config={
            "task_description": task_description,
            "agent_type": agent_type,
            "provider": provider,
        },
    )


def create_workflow_job(
    name: str,
    cron: str,
    workflow_id: str,
) -> ScheduledJob:
    """Create a ScheduledJob that triggers a workflow on a cron schedule."""
    return ScheduledJob(
        name=name,
        job_type=JobType.WORKFLOW,
        cron=cron,
        config={"workflow_id": workflow_id},
    )


def create_skill_job(
    name: str,
    cron: str,
    skill: str,
    tool: str,
    arguments: dict,
) -> ScheduledJob:
    """Create a ScheduledJob that calls a skill tool on a cron schedule."""
    return ScheduledJob(
        name=name,
        job_type=JobType.SKILL,
        cron=cron,
        config={
            "skill": skill,
            "tool": tool,
            "arguments": arguments,
        },
    )
