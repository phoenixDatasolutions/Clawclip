"""TicketSystem — atomic ticket lifecycle management with immutable audit log."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from clawclip.company.models import Ticket, TicketEvent
from clawclip.core.events import EventBus

if TYPE_CHECKING:
    from clawclip.company.store import CompanyStore

logger = logging.getLogger(__name__)


class TicketSystem:
    """Manages the full lifecycle of work tickets within a company.

    Key properties:
    - ``checkout_ticket`` is atomic per ticket_id (asyncio.Lock per ticket).
    - The event log is immutable — ``add_event`` always appends, never modifies.
    - Failed tickets are reset to "open" for retry rather than permanently closed.
    """

    def __init__(self, company_id: str, store: "CompanyStore", event_bus: EventBus) -> None:
        self._company_id = company_id
        self._store = store
        self._event_bus = event_bus
        self._checkout_locks: dict[str, asyncio.Lock] = {}

    def _checkout_lock(self, ticket_id: str) -> asyncio.Lock:
        if ticket_id not in self._checkout_locks:
            self._checkout_locks[ticket_id] = asyncio.Lock()
        return self._checkout_locks[ticket_id]

    # ── CRUD ─────────────────────────────────────────────────────

    async def create_ticket(
        self,
        title: str,
        description: str,
        assigned_to: str,
        goal_id: str | None = None,
        budget_usd: float = 1.0,
        created_by: str = "human",
        priority: int = 0,
        tags: list[str] | None = None,
        parent_ticket_id: str | None = None,
    ) -> Ticket:
        """Create a new ticket and append a 'created' event."""
        ticket = Ticket(
            id=str(uuid4()),
            company_id=self._company_id,
            goal_id=goal_id,
            title=title,
            description=description,
            assigned_to=assigned_to,
            status="open",
            priority=priority,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            budget_usd=budget_usd,
            tags=tags or [],
            parent_ticket_id=parent_ticket_id,
        )
        await self._store.save_ticket(ticket)
        await self.add_event(
            ticket_id=ticket.id,
            event_type="created",
            actor=created_by,
            content=f"Ticket '{title}' created",
            data={"assigned_to": assigned_to, "budget_usd": budget_usd},
        )
        logger.info(
            "TicketSystem[%s]: created ticket '%s' (%s) → %s",
            self._company_id, title, ticket.id, assigned_to,
        )
        return ticket

    async def get_ticket(self, ticket_id: str) -> Ticket | None:
        tickets = {t.id: t for t in self._store.load_tickets(self._company_id)}
        return tickets.get(ticket_id)

    async def list_tickets(
        self,
        status: str | None = None,
        assigned_to: str | None = None,
    ) -> list[Ticket]:
        """List tickets with optional filters."""
        tickets = self._store.load_tickets(self._company_id)
        if status is not None:
            tickets = [t for t in tickets if t.status == status]
        if assigned_to is not None:
            tickets = [t for t in tickets if t.assigned_to == assigned_to]
        return sorted(tickets, key=lambda t: (-t.priority, t.created_at))

    # ── Lifecycle ─────────────────────────────────────────────────

    async def checkout_ticket(self, ticket_id: str, agent_name: str) -> bool:
        """Atomically claim a ticket for an agent.

        Returns False if the ticket is already in_progress (checked out by
        another agent). Uses a per-ticket asyncio.Lock to prevent races.
        """
        lock = self._checkout_lock(ticket_id)
        async with lock:
            ticket = await self.get_ticket(ticket_id)
            if ticket is None:
                logger.warning("checkout_ticket: ticket %s not found", ticket_id)
                return False
            if ticket.status == "in_progress":
                logger.debug(
                    "checkout_ticket: ticket %s already in_progress", ticket_id
                )
                return False
            ticket.status = "in_progress"
            ticket.started_at = datetime.now(timezone.utc)
            await self._store.save_ticket(ticket)
            await self.add_event(
                ticket_id=ticket_id,
                event_type="started",
                actor=agent_name,
                content=f"Agent '{agent_name}' checked out ticket",
            )
        return True

    async def complete_ticket(
        self, ticket_id: str, agent_name: str, result: str
    ) -> None:
        """Mark a ticket as done and record the completion event."""
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            logger.warning("complete_ticket: ticket %s not found", ticket_id)
            return
        ticket.status = "done"
        ticket.completed_at = datetime.now(timezone.utc)
        await self._store.save_ticket(ticket)
        await self.add_event(
            ticket_id=ticket_id,
            event_type="completed",
            actor=agent_name,
            content=f"Ticket completed by '{agent_name}'",
            data={"result": result},
        )
        logger.info("TicketSystem[%s]: ticket %s completed", self._company_id, ticket_id)

    async def fail_ticket(
        self, ticket_id: str, agent_name: str, error: str
    ) -> None:
        """Mark a ticket as failed and reset it to 'open' for retry."""
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            logger.warning("fail_ticket: ticket %s not found", ticket_id)
            return
        ticket.status = "open"  # reset for retry
        ticket.started_at = None
        ticket.retry_count += 1
        await self._store.save_ticket(ticket)
        await self.add_event(
            ticket_id=ticket_id,
            event_type="failed",
            actor=agent_name,
            content=f"Ticket failed: {error}",
            data={"error": error, "retry_count": ticket.retry_count},
        )
        logger.warning(
            "TicketSystem[%s]: ticket %s failed (retry #%d)",
            self._company_id, ticket_id, ticket.retry_count,
        )

    # ── Sub-tickets ───────────────────────────────────────────────

    async def create_sub_ticket(
        self,
        parent_ticket_id: str,
        title: str,
        description: str,
        assigned_to: str,
        budget_usd: float | None = None,
        created_by: str = "agent",
    ) -> Ticket:
        """Create a sub-ticket inheriting budget from the parent."""
        parent = await self.get_ticket(parent_ticket_id)
        if parent is None:
            raise ValueError(f"Parent ticket {parent_ticket_id} not found")

        # Sub-ticket gets a fraction of parent's remaining budget if not specified
        sub_budget = budget_usd if budget_usd is not None else (
            max(0.0, parent.budget_usd - parent.cost_used_usd) * 0.5
        )

        return await self.create_ticket(
            title=title,
            description=description,
            assigned_to=assigned_to,
            goal_id=parent.goal_id,
            budget_usd=sub_budget,
            created_by=created_by,
            priority=parent.priority,
            tags=list(parent.tags),
            parent_ticket_id=parent_ticket_id,
        )

    # ── Budget ────────────────────────────────────────────────────

    async def get_ticket_cost(self, ticket_id: str) -> float:
        """Sum cost from all 'cost' events on this ticket."""
        events = await self.get_events(ticket_id)
        return sum(e.data.get("cost_usd", 0.0) for e in events if e.event_type == "cost")

    async def update_ticket_cost(self, ticket_id: str, additional_cost: float) -> None:
        """Record an incremental cost against the ticket."""
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            return
        ticket.cost_used_usd += additional_cost
        await self._store.save_ticket(ticket)
        await self.add_event(
            ticket_id=ticket_id,
            event_type="cost",
            actor="system",
            content=f"Cost recorded: ${additional_cost:.4f}",
            data={"cost_usd": additional_cost, "total_cost_usd": ticket.cost_used_usd},
        )

        # Warn if approaching budget limit
        if ticket.budget_usd > 0 and ticket.cost_used_usd / ticket.budget_usd >= 0.8:
            await self.add_event(
                ticket_id=ticket_id,
                event_type="budget_warning",
                actor="system",
                content=(
                    f"Budget warning: ${ticket.cost_used_usd:.4f} / ${ticket.budget_usd:.2f} "
                    f"({ticket.cost_used_usd / ticket.budget_usd:.0%})"
                ),
                data={
                    "used": ticket.cost_used_usd,
                    "limit": ticket.budget_usd,
                    "percentage": ticket.cost_used_usd / ticket.budget_usd,
                },
            )

    # ── Immutable event log ───────────────────────────────────────

    async def add_event(
        self,
        ticket_id: str,
        event_type: str,
        actor: str,
        content: str,
        data: dict | None = None,
    ) -> TicketEvent:
        """Append a new event to the immutable audit log.

        This ALWAYS appends — existing events are never modified.
        """
        event = TicketEvent(
            id=str(uuid4()),
            ticket_id=ticket_id,
            event_type=event_type,
            actor=actor,
            content=content,
            data=data or {},
            created_at=datetime.now(timezone.utc),
        )
        await self._store.append_event(self._company_id, event)
        return event

    async def get_events(self, ticket_id: str) -> list[TicketEvent]:
        """Return all events for a ticket, oldest first."""
        return self._store.load_events(self._company_id, ticket_id=ticket_id)
