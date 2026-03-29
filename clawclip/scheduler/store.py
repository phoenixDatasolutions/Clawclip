"""ClawClip Scheduler — persistent JSON-backed job store."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from clawclip.scheduler.jobs import JobType, ScheduledJob

logger = logging.getLogger(__name__)

_DT_FMT = "%Y-%m-%dT%H:%M:%S.%f%z"


def _serialize_job(job: ScheduledJob) -> dict:
    """Convert a ScheduledJob to a JSON-serialisable dict."""
    return {
        "id": job.id,
        "name": job.name,
        "job_type": job.job_type.value,
        "cron": job.cron,
        "config": job.config,
        "enabled": job.enabled,
        "last_run": job.last_run.isoformat() if job.last_run else None,
        "next_run": job.next_run.isoformat() if job.next_run else None,
    }


def _deserialize_job(data: dict) -> ScheduledJob:
    """Restore a ScheduledJob from a stored dict."""

    def _dt(val: str | None) -> datetime | None:
        if val is None:
            return None
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None

    return ScheduledJob(
        id=data["id"],
        name=data.get("name", ""),
        job_type=JobType(data.get("job_type", "agent_task")),
        cron=data.get("cron", "* * * * *"),
        config=data.get("config", {}),
        enabled=data.get("enabled", True),
        last_run=_dt(data.get("last_run")),
        next_run=_dt(data.get("next_run")),
    )


class JobStore:
    """Thread-safe, file-backed store for ScheduledJob objects.

    Jobs are persisted as a JSON array at *jobs_file*.  All mutating
    operations acquire an asyncio.Lock so that concurrent coroutines cannot
    corrupt the file.
    """

    def __init__(self, jobs_file: str = "data/scheduler_jobs.json") -> None:
        self._path = Path(jobs_file)
        self._lock = asyncio.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── private helpers ───────────────────────────────────────────

    def _read_all(self) -> dict[str, dict]:
        """Return raw dict keyed by job id (synchronous, call under lock)."""
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return {item["id"]: item for item in data} if isinstance(data, list) else {}
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Could not read job store %s: %s", self._path, exc)
            return {}

    def _write_all(self, jobs: dict[str, dict]) -> None:
        """Persist all jobs (synchronous, call under lock)."""
        try:
            with self._path.open("w", encoding="utf-8") as fh:
                json.dump(list(jobs.values()), fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.error("Could not write job store %s: %s", self._path, exc)

    # ── public API ────────────────────────────────────────────────

    async def save_job(self, job: ScheduledJob) -> None:
        """Insert or replace a job in the store."""
        async with self._lock:
            jobs = self._read_all()
            jobs[job.id] = _serialize_job(job)
            self._write_all(jobs)

    async def delete_job(self, job_id: str) -> None:
        """Remove a job by id (no-op if missing)."""
        async with self._lock:
            jobs = self._read_all()
            jobs.pop(job_id, None)
            self._write_all(jobs)

    async def list_jobs(self) -> list[ScheduledJob]:
        """Return all stored jobs."""
        async with self._lock:
            jobs = self._read_all()
        return [_deserialize_job(v) for v in jobs.values()]

    async def get_job(self, job_id: str) -> ScheduledJob | None:
        """Return a single job by id, or None if not found."""
        async with self._lock:
            jobs = self._read_all()
        raw = jobs.get(job_id)
        return _deserialize_job(raw) if raw else None

    async def update_job(self, job: ScheduledJob) -> None:
        """Update an existing job (alias for save_job — upsert semantics)."""
        await self.save_job(job)
