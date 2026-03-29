"""CompanyStore — JSON-based persistence for all company data.

All writes are atomic (write to .tmp then rename). Each file type has its
own asyncio.Lock to prevent concurrent corruption.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clawclip.company.models import (
    Budget,
    Company,
    Goal,
    OrgNode,
    Ticket,
    TicketEvent,
)

logger = logging.getLogger(__name__)

_DATA_ROOT = Path("data/companies")


def _dt_to_str(obj: Any) -> Any:
    """JSON default serialiser — converts datetime → ISO string, set → list."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class CompanyStore:
    """Filesystem-backed store for all company orchestration data.

    Layout::

        data/companies/{company_id}/
            company.json
            org_chart.json
            goals.json
            tickets.json
            events.json       # append-only audit log
            budgets.json
            heartbeats.json
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    # ── Internal helpers ────────────────────────────────────────

    def _company_dir(self, company_id: str) -> Path:
        p = _DATA_ROOT / company_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _file_lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _file_path(self, company_id: str, name: str) -> Path:
        return self._company_dir(company_id) / name

    async def _write_json(self, path: Path, data: Any) -> None:
        """Atomic write: serialise to .tmp then rename."""
        lock = self._file_lock(str(path))
        async with lock:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, default=_dt_to_str, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    def _read_json(self, path: Path, default: Any = None) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read %s, returning default", path)
            return default

    # ── Company ─────────────────────────────────────────────────

    async def save_company(self, company: Company) -> None:
        path = self._file_path(company.id, "company.json")
        await self._write_json(path, {
            "id": company.id,
            "name": company.name,
            "mission": company.mission,
            "created_at": company.created_at,
            "settings": company.settings,
        })

    def load_company(self, company_id: str) -> Company | None:
        path = self._file_path(company_id, "company.json")
        data = self._read_json(path)
        if not data:
            return None
        return Company(
            id=data["id"],
            name=data["name"],
            mission=data["mission"],
            created_at=_ensure_utc(_parse_dt(data.get("created_at"))) or datetime.now(timezone.utc),
            settings=data.get("settings", {}),
        )

    def load_all_companies(self) -> list[Company]:
        companies: list[Company] = []
        if not _DATA_ROOT.exists():
            return companies
        for entry in _DATA_ROOT.iterdir():
            if entry.is_dir():
                company = self.load_company(entry.name)
                if company:
                    companies.append(company)
        return companies

    # ── OrgChart ─────────────────────────────────────────────────

    async def save_org_node(self, node: OrgNode) -> None:
        path = self._file_path(node.company_id, "org_chart.json")
        lock = self._file_lock(str(path))
        async with lock:
            nodes = self._read_json(path, {})
            nodes[node.id] = {
                "id": node.id,
                "company_id": node.company_id,
                "agent_name": node.agent_name,
                "role_title": node.role_title,
                "description": node.description,
                "parent_id": node.parent_id,
                "allowed_skills": node.allowed_skills,
                "budget_limit_usd": node.budget_limit_usd,
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(nodes, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    async def delete_org_node(self, company_id: str, node_id: str) -> None:
        path = self._file_path(company_id, "org_chart.json")
        lock = self._file_lock(str(path))
        async with lock:
            nodes = self._read_json(path, {})
            nodes.pop(node_id, None)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(nodes, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    def load_org_nodes(self, company_id: str) -> list[OrgNode]:
        path = self._file_path(company_id, "org_chart.json")
        data = self._read_json(path, {})
        return [
            OrgNode(
                id=d["id"],
                company_id=d["company_id"],
                agent_name=d["agent_name"],
                role_title=d["role_title"],
                description=d["description"],
                parent_id=d.get("parent_id"),
                allowed_skills=d.get("allowed_skills", []),
                budget_limit_usd=d.get("budget_limit_usd", 10.0),
            )
            for d in data.values()
        ]

    # ── Goals ────────────────────────────────────────────────────

    async def save_goal(self, goal: Goal) -> None:
        path = self._file_path(goal.company_id, "goals.json")
        lock = self._file_lock(str(path))
        async with lock:
            goals = self._read_json(path, {})
            goals[goal.id] = {
                "id": goal.id,
                "company_id": goal.company_id,
                "title": goal.title,
                "description": goal.description,
                "status": goal.status,
                "priority": goal.priority,
                "created_at": _dt_to_str(goal.created_at),
                "completed_at": _dt_to_str(goal.completed_at) if goal.completed_at else None,
                "parent_goal_id": goal.parent_goal_id,
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(goals, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    def load_goals(self, company_id: str) -> list[Goal]:
        path = self._file_path(company_id, "goals.json")
        data = self._read_json(path, {})
        return [
            Goal(
                id=d["id"],
                company_id=d["company_id"],
                title=d["title"],
                description=d["description"],
                status=d["status"],
                priority=d.get("priority", 0),
                created_at=_ensure_utc(_parse_dt(d.get("created_at"))) or datetime.now(timezone.utc),
                completed_at=_ensure_utc(_parse_dt(d.get("completed_at"))),
                parent_goal_id=d.get("parent_goal_id"),
            )
            for d in data.values()
        ]

    # ── Tickets ──────────────────────────────────────────────────

    async def save_ticket(self, ticket: Ticket) -> None:
        path = self._file_path(ticket.company_id, "tickets.json")
        lock = self._file_lock(str(path))
        async with lock:
            tickets = self._read_json(path, {})
            tickets[ticket.id] = {
                "id": ticket.id,
                "company_id": ticket.company_id,
                "goal_id": ticket.goal_id,
                "title": ticket.title,
                "description": ticket.description,
                "assigned_to": ticket.assigned_to,
                "status": ticket.status,
                "priority": ticket.priority,
                "created_by": ticket.created_by,
                "created_at": _dt_to_str(ticket.created_at),
                "started_at": _dt_to_str(ticket.started_at) if ticket.started_at else None,
                "completed_at": _dt_to_str(ticket.completed_at) if ticket.completed_at else None,
                "budget_usd": ticket.budget_usd,
                "cost_used_usd": ticket.cost_used_usd,
                "parent_ticket_id": ticket.parent_ticket_id,
                "tags": ticket.tags,
                "retry_count": ticket.retry_count,
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(tickets, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    def load_tickets(self, company_id: str) -> list[Ticket]:
        path = self._file_path(company_id, "tickets.json")
        data = self._read_json(path, {})
        return [
            Ticket(
                id=d["id"],
                company_id=d["company_id"],
                goal_id=d.get("goal_id"),
                title=d["title"],
                description=d["description"],
                assigned_to=d["assigned_to"],
                status=d["status"],
                priority=d.get("priority", 0),
                created_by=d.get("created_by", "human"),
                created_at=_ensure_utc(_parse_dt(d.get("created_at"))) or datetime.now(timezone.utc),
                started_at=_ensure_utc(_parse_dt(d.get("started_at"))),
                completed_at=_ensure_utc(_parse_dt(d.get("completed_at"))),
                budget_usd=d.get("budget_usd", 1.0),
                cost_used_usd=d.get("cost_used_usd", 0.0),
                parent_ticket_id=d.get("parent_ticket_id"),
                tags=d.get("tags", []),
                retry_count=d.get("retry_count", 0),
            )
            for d in data.values()
        ]

    # ── Events (append-only) ─────────────────────────────────────

    async def append_event(self, company_id: str, event: TicketEvent) -> None:
        """ALWAYS appends. Never overwrites existing events."""
        path = self._file_path(company_id, "events.json")
        lock = self._file_lock(str(path))
        async with lock:
            events = self._read_json(path, [])
            events.append({
                "id": event.id,
                "ticket_id": event.ticket_id,
                "event_type": event.event_type,
                "actor": event.actor,
                "content": event.content,
                "data": event.data,
                "created_at": _dt_to_str(event.created_at),
            })
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(events, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    def load_events(self, company_id: str, ticket_id: str | None = None) -> list[TicketEvent]:
        path = self._file_path(company_id, "events.json")
        data = self._read_json(path, [])
        events = [
            TicketEvent(
                id=d["id"],
                ticket_id=d["ticket_id"],
                event_type=d["event_type"],
                actor=d["actor"],
                content=d["content"],
                data=d.get("data", {}),
                created_at=_ensure_utc(_parse_dt(d.get("created_at"))) or datetime.now(timezone.utc),
            )
            for d in data
        ]
        if ticket_id is not None:
            events = [e for e in events if e.ticket_id == ticket_id]
        return events

    # ── Budget ───────────────────────────────────────────────────

    async def save_budget(self, budget: Budget) -> None:
        path = self._file_path(budget.company_id, "budgets.json")
        await self._write_json(path, {
            "company_id": budget.company_id,
            "period": budget.period,
            "limit_usd": budget.limit_usd,
            "used_usd": budget.used_usd,
            "agent_budgets": budget.agent_budgets,
            "agent_used": budget.agent_used,
            "throttled_agents": list(budget.throttled_agents),
        })

    def load_budget(self, company_id: str) -> Budget | None:
        path = self._file_path(company_id, "budgets.json")
        data = self._read_json(path)
        if not data:
            return None
        return Budget(
            company_id=data["company_id"],
            period=data.get("period", "monthly"),
            limit_usd=data.get("limit_usd", 100.0),
            used_usd=data.get("used_usd", 0.0),
            agent_budgets=data.get("agent_budgets", {}),
            agent_used=data.get("agent_used", {}),
            throttled_agents=set(data.get("throttled_agents", [])),
        )

    # ── Heartbeats ───────────────────────────────────────────────

    async def save_heartbeat(self, record: dict) -> None:
        company_id = record["company_id"]
        path = self._file_path(company_id, "heartbeats.json")
        lock = self._file_lock(str(path))
        async with lock:
            heartbeats = self._read_json(path, {})
            heartbeats[record["agent_name"]] = record
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(heartbeats, default=_dt_to_str, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    def load_heartbeats(self, company_id: str) -> list[dict]:
        path = self._file_path(company_id, "heartbeats.json")
        data = self._read_json(path, {})
        return list(data.values())
