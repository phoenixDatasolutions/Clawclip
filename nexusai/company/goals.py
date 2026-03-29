"""GoalManager — create, track, and query company-level goals."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from nexusai.company.models import Goal

if TYPE_CHECKING:
    from nexusai.company.store import CompanyStore

logger = logging.getLogger(__name__)


class GoalManager:
    """Manages strategic goals for a company.

    Goals form a tree (via parent_goal_id) and track progress by
    aggregating the completion status of their associated tickets.
    """

    def __init__(self, company_id: str, store: "CompanyStore") -> None:
        self._company_id = company_id
        self._store = store

    # ── CRUD ─────────────────────────────────────────────────────

    async def create_goal(
        self,
        title: str,
        description: str,
        priority: int = 0,
        parent_id: str | None = None,
    ) -> Goal:
        """Create a new goal and persist it."""
        goal = Goal(
            id=str(uuid4()),
            company_id=self._company_id,
            title=title,
            description=description,
            status="active",
            priority=priority,
            created_at=datetime.now(timezone.utc),
            parent_goal_id=parent_id,
        )
        await self._store.save_goal(goal)
        logger.info("GoalManager[%s]: created goal '%s' (%s)", self._company_id, title, goal.id)
        return goal

    async def complete_goal(self, goal_id: str) -> None:
        """Mark a goal as completed."""
        goals = {g.id: g for g in self._store.load_goals(self._company_id)}
        goal = goals.get(goal_id)
        if goal is None:
            logger.warning("GoalManager: complete_goal called for unknown goal %s", goal_id)
            return
        goal.status = "completed"
        goal.completed_at = datetime.now(timezone.utc)
        await self._store.save_goal(goal)

    async def pause_goal(self, goal_id: str) -> None:
        """Pause an active goal."""
        goals = {g.id: g for g in self._store.load_goals(self._company_id)}
        goal = goals.get(goal_id)
        if goal is None:
            logger.warning("GoalManager: pause_goal called for unknown goal %s", goal_id)
            return
        goal.status = "paused"
        await self._store.save_goal(goal)

    async def list_goals(self, status: str | None = None) -> list[Goal]:
        """List all goals, optionally filtered by status."""
        goals = self._store.load_goals(self._company_id)
        if status is not None:
            goals = [g for g in goals if g.status == status]
        return sorted(goals, key=lambda g: (-g.priority, g.created_at))

    async def get_goal(self, goal_id: str) -> Goal | None:
        goals = {g.id: g for g in self._store.load_goals(self._company_id)}
        return goals.get(goal_id)

    async def get_active_goals(self) -> list[Goal]:
        """Return all currently active goals, ordered by priority."""
        return await self.list_goals(status="active")

    # ── Progress ─────────────────────────────────────────────────

    async def get_goal_progress(self, goal_id: str) -> dict:
        """Return progress metrics for a goal by aggregating its tickets.

        Returns::

            {
                "total_tickets": int,
                "completed_tickets": int,
                "in_progress_tickets": int,
                "cost_used_usd": float,
            }
        """
        tickets = self._store.load_tickets(self._company_id)
        related = [t for t in tickets if t.goal_id == goal_id]
        return {
            "total_tickets": len(related),
            "completed_tickets": sum(1 for t in related if t.status == "done"),
            "in_progress_tickets": sum(1 for t in related if t.status == "in_progress"),
            "cost_used_usd": sum(t.cost_used_usd for t in related),
        }
