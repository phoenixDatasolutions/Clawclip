"""CompanyManager — top-level facade for all company orchestration features."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from clawclip.company.budgets import BudgetManager
from clawclip.company.goals import GoalManager
from clawclip.company.governance import GovernanceManager, GovernanceRule
from clawclip.company.heartbeat import HeartbeatManager
from clawclip.company.models import Budget, Company, Ticket
from clawclip.company.org_chart import OrgChart, create_default_chart
from clawclip.company.store import CompanyStore
from clawclip.company.tickets import TicketSystem
from clawclip.core.events import EventBus
from clawclip.core.types import AgentResult

logger = logging.getLogger(__name__)


class CompanyManager:
    """Top-level entry point for all company orchestration features.

    Provides:
    - Company lifecycle (create / get / list)
    - Per-company sub-systems: org chart, tickets, goals, budgets, governance
    - High-level ``submit_task`` and ``run_ticket`` workflows
    """

    def __init__(
        self,
        event_bus: EventBus,
        agent_engine: Any = None,
    ) -> None:
        self._event_bus = event_bus
        self._agent_engine = agent_engine
        self._store = CompanyStore()
        self._heartbeat_manager = HeartbeatManager(self._store)

        # Per-company subsystem caches
        self._org_charts: dict[str, OrgChart] = {}
        self._ticket_systems: dict[str, TicketSystem] = {}
        self._goal_managers: dict[str, GoalManager] = {}
        self._budget_managers: dict[str, BudgetManager] = {}
        self._governance_managers: dict[str, GovernanceManager] = {}

    # ── Company lifecycle ─────────────────────────────────────────

    async def create_company(self, name: str, mission: str) -> Company:
        """Create a new company with a default org chart and budget."""
        company = Company(
            id=str(uuid4()),
            name=name,
            mission=mission,
            created_at=datetime.now(timezone.utc),
        )
        await self._store.save_company(company)

        # Bootstrap default org chart
        await create_default_chart(company.id, self._store)

        # Bootstrap default budget
        budget = Budget(
            company_id=company.id,
            period="monthly",
            limit_usd=100.0,
        )
        await self._store.save_budget(budget)

        logger.info("CompanyManager: created company '%s' (%s)", name, company.id)
        return company

    async def get_company(self, company_id: str) -> Company | None:
        return self._store.load_company(company_id)

    async def list_companies(self) -> list[Company]:
        return self._store.load_all_companies()

    # ── Sub-system accessors ──────────────────────────────────────

    async def get_org_chart(self, company_id: str) -> OrgChart:
        if company_id not in self._org_charts:
            self._org_charts[company_id] = OrgChart(company_id, self._store)
        return self._org_charts[company_id]

    async def get_ticket_system(self, company_id: str) -> TicketSystem:
        if company_id not in self._ticket_systems:
            self._ticket_systems[company_id] = TicketSystem(
                company_id, self._store, self._event_bus
            )
        return self._ticket_systems[company_id]

    async def get_goal_manager(self, company_id: str) -> GoalManager:
        if company_id not in self._goal_managers:
            self._goal_managers[company_id] = GoalManager(company_id, self._store)
        return self._goal_managers[company_id]

    async def get_budget_manager(self, company_id: str) -> BudgetManager:
        if company_id not in self._budget_managers:
            self._budget_managers[company_id] = BudgetManager(company_id, self._store)
        return self._budget_managers[company_id]

    async def get_governance(self, company_id: str) -> GovernanceManager:
        if company_id not in self._governance_managers:
            self._governance_managers[company_id] = GovernanceManager(
                rules=[
                    GovernanceRule.MAX_DEPTH_LIMIT,
                    GovernanceRule.REQUIRE_APPROVAL_FOR_EXTERNAL_CALLS,
                ]
            )
        return self._governance_managers[company_id]

    def get_heartbeat_manager(self) -> HeartbeatManager:
        return self._heartbeat_manager

    # ── High-level workflows ──────────────────────────────────────

    async def submit_task(
        self,
        company_id: str,
        title: str,
        description: str,
        goal_id: str | None = None,
        priority: int = 0,
        budget_usd: float = 5.0,
    ) -> Ticket:
        """Create a ticket assigned to the CEO-level agent and return it.

        The ticket is not immediately executed — call ``run_ticket`` to
        execute it through the agent engine.
        """
        org_chart = await self.get_org_chart(company_id)
        await org_chart.list_roles()  # warm cache

        root_roles = await org_chart.get_root_roles()
        if root_roles:
            assigned_to = root_roles[0].id
        else:
            assigned_to = "coordinator"

        ticket_system = await self.get_ticket_system(company_id)
        ticket = await ticket_system.create_ticket(
            title=title,
            description=description,
            assigned_to=assigned_to,
            goal_id=goal_id,
            budget_usd=budget_usd,
            created_by="human",
            priority=priority,
        )
        logger.info(
            "CompanyManager[%s]: submitted task '%s' → ticket %s",
            company_id, title, ticket.id,
        )
        return ticket

    async def run_ticket(self, company_id: str, ticket_id: str) -> AgentResult:
        """Execute a ticket through the full lifecycle.

        Steps:
        1. Check budget.
        2. Checkout (atomic).
        3. Resolve org node → agent type.
        4. Run agent via engine with heartbeat pings.
        5. Record cost.
        6. Complete or fail ticket.
        """
        ticket_system = await self.get_ticket_system(company_id)
        budget_manager = await self.get_budget_manager(company_id)
        org_chart = await self.get_org_chart(company_id)
        await org_chart.list_roles()  # warm cache

        ticket = await ticket_system.get_ticket(ticket_id)
        if ticket is None:
            return AgentResult(
                success=False,
                output=f"Ticket {ticket_id} not found",
            )

        # Resolve org node
        org_node = await org_chart.get_role(ticket.assigned_to)
        agent_name = org_node.agent_name if org_node else "coordinator"

        # Budget check
        if not await budget_manager.check_ticket_budget(ticket_id, agent_name):
            await ticket_system.add_event(
                ticket_id=ticket_id,
                event_type="blocked",
                actor="system",
                content=f"Ticket blocked — agent '{agent_name}' has insufficient budget",
            )
            return AgentResult(
                success=False,
                output=f"Budget exceeded for agent '{agent_name}'",
            )

        # Atomic checkout
        checked_out = await ticket_system.checkout_ticket(ticket_id, agent_name)
        if not checked_out:
            return AgentResult(
                success=False,
                output=f"Ticket {ticket_id} already in progress",
            )

        # Run via integration layer if agent_engine is available
        if self._agent_engine is not None:
            from clawclip.company.integration import execute_ticket_as_agent

            company = await self.get_company(company_id)
            if company is None:
                company = Company(
                    id=company_id, name="", mission="",
                    created_at=datetime.now(timezone.utc),
                )

            try:
                result = await execute_ticket_as_agent(
                    ticket=ticket,
                    org_node=org_node,
                    company_manager=self,
                    agent_engine=self._agent_engine,
                    skill_manager=getattr(self._agent_engine, "_skill_manager", None),
                )
            except Exception as exc:
                await ticket_system.fail_ticket(ticket_id, agent_name, str(exc))
                return AgentResult(success=False, output=str(exc))

            if result.success:
                await ticket_system.complete_ticket(ticket_id, agent_name, result.output)
            else:
                await ticket_system.fail_ticket(ticket_id, agent_name, result.output)

            await budget_manager.record_cost(agent_name, result.cost_usd, ticket_id)
            await ticket_system.update_ticket_cost(ticket_id, result.cost_usd)
            return result

        # No engine — return stub result
        await ticket_system.complete_ticket(ticket_id, agent_name, "No agent engine configured")
        return AgentResult(
            success=True,
            output="Ticket completed (no agent engine configured)",
            agent_type=agent_name,
        )

    # ── Heartbeat lifecycle ───────────────────────────────────────

    def start_heartbeat_monitor(self) -> None:
        """Start the background heartbeat sweep."""
        self._heartbeat_manager.start_background_task()

    def stop_heartbeat_monitor(self) -> None:
        """Stop the background heartbeat sweep."""
        self._heartbeat_manager.stop_background_task()
