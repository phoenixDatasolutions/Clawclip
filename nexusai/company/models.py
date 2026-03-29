"""Company orchestration data models — pure dataclasses, no ORM dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Company:
    """An AI company with a mission and org structure."""
    id: str
    name: str
    mission: str  # The company's high-level purpose
    created_at: datetime
    settings: dict = field(default_factory=dict)


@dataclass
class OrgNode:
    """A single role/position in the company's org chart."""
    id: str
    company_id: str
    agent_name: str       # e.g. "coordinator", "code_agent"
    role_title: str       # e.g. "Chief Executive Officer"
    description: str      # Role's responsibilities and scope
    parent_id: str | None  # None = top of hierarchy
    allowed_skills: list[str]
    budget_limit_usd: float = 10.0  # per-task budget limit


@dataclass
class Goal:
    """A high-level objective that tickets roll up into."""
    id: str
    company_id: str
    title: str
    description: str
    status: str  # "active", "completed", "paused"
    priority: int = 0
    created_at: datetime = field(default_factory=_utcnow)
    completed_at: datetime | None = None
    parent_goal_id: str | None = None  # For sub-goals


@dataclass
class Ticket:
    """A unit of work assigned to an agent role."""
    id: str
    company_id: str
    goal_id: str | None   # Which goal this rolls up to
    title: str
    description: str
    assigned_to: str      # OrgNode.id (which agent role)
    status: str           # "open", "in_progress", "review", "done", "blocked"
    priority: int = 0
    created_by: str = "human"  # "human" or agent_name
    created_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    budget_usd: float = 1.0    # Per-ticket budget allocation
    cost_used_usd: float = 0.0  # Actual cost so far
    parent_ticket_id: str | None = None  # Sub-tickets
    tags: list[str] = field(default_factory=list)
    retry_count: int = 0


@dataclass
class TicketEvent:
    """Immutable audit log entry — append-only, never modified."""
    id: str
    ticket_id: str
    event_type: str       # "created", "assigned", "started", "tool_called",
                          # "message", "completed", "failed", "budget_warning"
    actor: str            # "human" or agent_name
    content: str          # Human-readable description
    data: dict = field(default_factory=dict)  # Structured data
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Budget:
    """Company-wide and per-agent budget tracking."""
    company_id: str
    period: str           # "daily", "weekly", "monthly", "per_task"
    limit_usd: float
    used_usd: float = 0.0
    agent_budgets: dict[str, float] = field(default_factory=dict)  # agent_name → limit
    agent_used: dict[str, float] = field(default_factory=dict)     # agent_name → used
    throttled_agents: set[str] = field(default_factory=set)        # agents over budget
