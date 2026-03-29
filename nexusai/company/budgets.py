"""BudgetManager — per-agent and company-wide spend tracking with throttling."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from nexusai.company.models import Budget

if TYPE_CHECKING:
    from nexusai.company.store import CompanyStore

logger = logging.getLogger(__name__)

BUDGET_WARNING_THRESHOLD = 0.8  # warn at 80% usage
_DEFAULT_COMPANY_LIMIT = 100.0
_DEFAULT_PERIOD = "monthly"


class BudgetManager:
    """Tracks and enforces spending limits for agents and the company.

    Features:
    - Per-agent budget limits and spend tracking.
    - Automatic throttling when an agent exceeds its limit.
    - Budget reset by period (daily / weekly / monthly / per_task).
    - Per-ticket budget checking.
    """

    def __init__(self, company_id: str, store: "CompanyStore") -> None:
        self._company_id = company_id
        self._store = store

    # ── Load / initialise ────────────────────────────────────────

    async def get_budget(self, company_id: str) -> Budget:
        """Load or initialise the budget for the given company."""
        budget = self._store.load_budget(company_id)
        if budget is None:
            budget = Budget(
                company_id=company_id,
                period=_DEFAULT_PERIOD,
                limit_usd=_DEFAULT_COMPANY_LIMIT,
            )
            await self._store.save_budget(budget)
        return budget

    # ── Spend recording ──────────────────────────────────────────

    async def record_cost(
        self,
        agent_name: str,
        cost_usd: float,
        ticket_id: str | None = None,
    ) -> None:
        """Record a cost against the company and the named agent.

        Throttles the agent if they exceed their per-agent limit.
        """
        budget = await self.get_budget(self._company_id)

        # Update totals
        budget.used_usd += cost_usd
        budget.agent_used[agent_name] = budget.agent_used.get(agent_name, 0.0) + cost_usd

        # Check throttle
        agent_limit = budget.agent_budgets.get(agent_name)
        if agent_limit is not None:
            agent_used = budget.agent_used[agent_name]
            if agent_used >= agent_limit:
                budget.throttled_agents.add(agent_name)
                logger.warning(
                    "BudgetManager[%s]: agent '%s' throttled — used $%.4f / $%.2f",
                    self._company_id, agent_name, agent_used, agent_limit,
                )
            elif agent_used / agent_limit >= BUDGET_WARNING_THRESHOLD:
                logger.warning(
                    "BudgetManager[%s]: agent '%s' budget warning — %.0f%% used",
                    self._company_id, agent_name, agent_used / agent_limit * 100,
                )

        await self._store.save_budget(budget)

    async def is_throttled(self, agent_name: str) -> bool:
        """Return True if the agent is currently over budget and throttled."""
        budget = await self.get_budget(self._company_id)
        return agent_name in budget.throttled_agents

    async def reset_period(self, period: str) -> None:
        """Zero out usage counters for the given period.

        Intended to be called by a scheduler (e.g. daily cron).
        """
        budget = await self.get_budget(self._company_id)
        if budget.period != period:
            logger.debug(
                "BudgetManager[%s]: reset_period %s ignored (budget period is %s)",
                self._company_id, period, budget.period,
            )
            return
        budget.used_usd = 0.0
        budget.agent_used = {}
        budget.throttled_agents = set()
        await self._store.save_budget(budget)
        logger.info("BudgetManager[%s]: budget reset for period '%s'", self._company_id, period)

    # ── Status queries ────────────────────────────────────────────

    async def get_agent_budget_status(self, agent_name: str) -> dict:
        """Return budget status for a single agent.

        Returns::

            {
                "limit": float | None,
                "used": float,
                "remaining": float | None,
                "throttled": bool,
                "percentage": float | None,
            }
        """
        budget = await self.get_budget(self._company_id)
        limit = budget.agent_budgets.get(agent_name)
        used = budget.agent_used.get(agent_name, 0.0)
        remaining = (limit - used) if limit is not None else None
        percentage = (used / limit) if limit else None
        return {
            "limit": limit,
            "used": used,
            "remaining": remaining,
            "throttled": agent_name in budget.throttled_agents,
            "percentage": percentage,
        }

    async def get_company_budget_status(self) -> dict:
        """Return a full budget summary with per-agent breakdown.

        Returns::

            {
                "company_id": str,
                "period": str,
                "limit_usd": float,
                "used_usd": float,
                "remaining_usd": float,
                "percentage": float,
                "throttled_agents": list[str],
                "agents": {agent_name: {limit, used, remaining, throttled, percentage}},
            }
        """
        budget = await self.get_budget(self._company_id)
        all_agent_names = set(budget.agent_budgets) | set(budget.agent_used)
        agents = {}
        for name in all_agent_names:
            agents[name] = await self.get_agent_budget_status(name)

        return {
            "company_id": self._company_id,
            "period": budget.period,
            "limit_usd": budget.limit_usd,
            "used_usd": budget.used_usd,
            "remaining_usd": budget.limit_usd - budget.used_usd,
            "percentage": (budget.used_usd / budget.limit_usd) if budget.limit_usd else 0.0,
            "throttled_agents": list(budget.throttled_agents),
            "agents": agents,
        }

    async def check_ticket_budget(self, ticket_id: str, agent_name: str) -> bool:
        """Return True if both the ticket and the agent have budget remaining.

        Loads the ticket from store to get its budget/cost fields.
        """
        if await self.is_throttled(agent_name):
            logger.info(
                "BudgetManager: check_ticket_budget denied — agent '%s' is throttled",
                agent_name,
            )
            return False

        tickets = {t.id: t for t in self._store.load_tickets(self._company_id)}
        ticket = tickets.get(ticket_id)
        if ticket is None:
            logger.warning("BudgetManager: check_ticket_budget — ticket %s not found", ticket_id)
            return False

        has_ticket_budget = ticket.cost_used_usd < ticket.budget_usd
        if not has_ticket_budget:
            logger.info(
                "BudgetManager: check_ticket_budget denied — ticket %s over budget "
                "($%.4f / $%.2f)",
                ticket_id, ticket.cost_used_usd, ticket.budget_usd,
            )
        return has_ticket_budget
