"""Dashboard API routes for company orchestration features.

Mounts under the NexusAI dashboard FastAPI application and exposes:
- Company CRUD
- Org chart
- Goals
- Tickets
- Immutable event log
- Budget status
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────


class CreateCompanyRequest(BaseModel):
    name: str
    mission: str


class CreateGoalRequest(BaseModel):
    title: str
    description: str
    priority: int = 0
    parent_goal_id: str | None = None


class CreateTicketRequest(BaseModel):
    title: str
    description: str
    goal_id: str | None = None
    priority: int = 0
    budget_usd: float = 1.0
    tags: list[str] = []


class CompanyResponse(BaseModel):
    id: str
    name: str
    mission: str
    created_at: str
    settings: dict


class OrgNodeResponse(BaseModel):
    id: str
    agent_name: str
    role_title: str
    description: str
    parent_id: str | None
    allowed_skills: list[str]
    budget_limit_usd: float
    children: list["OrgNodeResponse"] = []


class GoalResponse(BaseModel):
    id: str
    company_id: str
    title: str
    description: str
    status: str
    priority: int
    created_at: str
    completed_at: str | None
    parent_goal_id: str | None


class TicketResponse(BaseModel):
    id: str
    company_id: str
    goal_id: str | None
    title: str
    description: str
    assigned_to: str
    status: str
    priority: int
    created_by: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    budget_usd: float
    cost_used_usd: float
    parent_ticket_id: str | None
    tags: list[str]
    retry_count: int


class TicketEventResponse(BaseModel):
    id: str
    ticket_id: str
    event_type: str
    actor: str
    content: str
    data: dict
    created_at: str


class BudgetStatusResponse(BaseModel):
    company_id: str
    period: str
    limit_usd: float
    used_usd: float
    remaining_usd: float
    percentage: float
    throttled_agents: list[str]
    agents: dict[str, Any]


# ── Router factory ────────────────────────────────────────────────


def create_company_router(company_manager: Any) -> APIRouter:
    """Return an APIRouter wired to the given CompanyManager instance.

    Args:
        company_manager: A ``CompanyManager`` instance.
    """
    router = APIRouter(prefix="/api/companies", tags=["companies"])

    def _dt_str(dt: Any) -> str | None:
        if dt is None:
            return None
        return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)

    # ── Companies ─────────────────────────────────────────────────

    @router.get("", response_model=list[CompanyResponse], summary="List all companies")
    async def list_companies() -> list[CompanyResponse]:
        companies = await company_manager.list_companies()
        return [
            CompanyResponse(
                id=c.id,
                name=c.name,
                mission=c.mission,
                created_at=_dt_str(c.created_at) or "",
                settings=c.settings,
            )
            for c in companies
        ]

    @router.post(
        "",
        response_model=CompanyResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create a new company",
    )
    async def create_company(body: CreateCompanyRequest) -> CompanyResponse:
        company = await company_manager.create_company(
            name=body.name, mission=body.mission
        )
        return CompanyResponse(
            id=company.id,
            name=company.name,
            mission=company.mission,
            created_at=_dt_str(company.created_at) or "",
            settings=company.settings,
        )

    # ── Org chart ─────────────────────────────────────────────────

    @router.get(
        "/{company_id}/org-chart",
        response_model=dict,
        summary="Get org chart as nested tree",
    )
    async def get_org_chart(company_id: str) -> dict:
        company = await company_manager.get_company(company_id)
        if company is None:
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        chart = await company_manager.get_org_chart(company_id)
        await chart.list_roles()  # warm cache
        return chart.to_tree()

    # ── Goals ─────────────────────────────────────────────────────

    @router.get(
        "/{company_id}/goals",
        response_model=list[GoalResponse],
        summary="List goals for a company",
    )
    async def list_goals(
        company_id: str,
        status: str | None = None,
    ) -> list[GoalResponse]:
        company = await company_manager.get_company(company_id)
        if company is None:
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        goal_manager = await company_manager.get_goal_manager(company_id)
        goals = await goal_manager.list_goals(status=status)
        return [
            GoalResponse(
                id=g.id,
                company_id=g.company_id,
                title=g.title,
                description=g.description,
                status=g.status,
                priority=g.priority,
                created_at=_dt_str(g.created_at) or "",
                completed_at=_dt_str(g.completed_at),
                parent_goal_id=g.parent_goal_id,
            )
            for g in goals
        ]

    @router.post(
        "/{company_id}/goals",
        response_model=GoalResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create a new goal",
    )
    async def create_goal(company_id: str, body: CreateGoalRequest) -> GoalResponse:
        company = await company_manager.get_company(company_id)
        if company is None:
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        goal_manager = await company_manager.get_goal_manager(company_id)
        goal = await goal_manager.create_goal(
            title=body.title,
            description=body.description,
            priority=body.priority,
            parent_id=body.parent_goal_id,
        )
        return GoalResponse(
            id=goal.id,
            company_id=goal.company_id,
            title=goal.title,
            description=goal.description,
            status=goal.status,
            priority=goal.priority,
            created_at=_dt_str(goal.created_at) or "",
            completed_at=_dt_str(goal.completed_at),
            parent_goal_id=goal.parent_goal_id,
        )

    # ── Tickets ───────────────────────────────────────────────────

    @router.get(
        "/{company_id}/tickets",
        response_model=list[TicketResponse],
        summary="List tickets (filterable by status and assigned agent)",
    )
    async def list_tickets(
        company_id: str,
        status: str | None = None,
        assigned_to: str | None = None,
    ) -> list[TicketResponse]:
        company = await company_manager.get_company(company_id)
        if company is None:
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        ts = await company_manager.get_ticket_system(company_id)
        tickets = await ts.list_tickets(status=status, assigned_to=assigned_to)
        return [_ticket_resp(t) for t in tickets]

    @router.post(
        "/{company_id}/tickets",
        response_model=TicketResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Submit a new task as a ticket",
    )
    async def submit_ticket(company_id: str, body: CreateTicketRequest) -> TicketResponse:
        company = await company_manager.get_company(company_id)
        if company is None:
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        ticket = await company_manager.submit_task(
            company_id=company_id,
            title=body.title,
            description=body.description,
            goal_id=body.goal_id,
            priority=body.priority,
            budget_usd=body.budget_usd,
        )
        return _ticket_resp(ticket)

    # ── Ticket events (immutable audit log) ───────────────────────

    @router.get(
        "/{company_id}/tickets/{ticket_id}/events",
        response_model=list[TicketEventResponse],
        summary="Get the immutable event log for a ticket",
    )
    async def get_ticket_events(
        company_id: str, ticket_id: str
    ) -> list[TicketEventResponse]:
        company = await company_manager.get_company(company_id)
        if company is None:
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        ts = await company_manager.get_ticket_system(company_id)
        ticket = await ts.get_ticket(ticket_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")
        events = await ts.get_events(ticket_id)
        return [
            TicketEventResponse(
                id=e.id,
                ticket_id=e.ticket_id,
                event_type=e.event_type,
                actor=e.actor,
                content=e.content,
                data=e.data,
                created_at=_dt_str(e.created_at) or "",
            )
            for e in events
        ]

    # ── Budget ────────────────────────────────────────────────────

    @router.get(
        "/{company_id}/budget",
        response_model=BudgetStatusResponse,
        summary="Get budget status for a company",
    )
    async def get_budget(company_id: str) -> BudgetStatusResponse:
        company = await company_manager.get_company(company_id)
        if company is None:
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
        budget_manager = await company_manager.get_budget_manager(company_id)
        status_data = await budget_manager.get_company_budget_status()
        return BudgetStatusResponse(**status_data)

    # ── Helpers ───────────────────────────────────────────────────

    def _ticket_resp(t: Any) -> TicketResponse:
        return TicketResponse(
            id=t.id,
            company_id=t.company_id,
            goal_id=t.goal_id,
            title=t.title,
            description=t.description,
            assigned_to=t.assigned_to,
            status=t.status,
            priority=t.priority,
            created_by=t.created_by,
            created_at=_dt_str(t.created_at) or "",
            started_at=_dt_str(t.started_at),
            completed_at=_dt_str(t.completed_at),
            budget_usd=t.budget_usd,
            cost_used_usd=t.cost_used_usd,
            parent_ticket_id=t.parent_ticket_id,
            tags=t.tags,
            retry_count=t.retry_count,
        )

    return router
