"""Unit tests for clawclip.company.tickets — TicketSystem."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from clawclip.company.models import Ticket, TicketEvent
from clawclip.company.tickets import TicketSystem
from clawclip.core.events import EventBus


# ── Fixtures / helpers ────────────────────────────────────────────────────────


def _make_store() -> MagicMock:
    """Return a mock CompanyStore with synchronous load methods returning lists."""
    store = MagicMock()
    store.save_ticket = AsyncMock()
    store.append_event = AsyncMock()
    store._tickets: dict[str, Ticket] = {}
    store._events: list[TicketEvent] = []

    def _load_tickets(company_id: str) -> list[Ticket]:
        return list(store._tickets.values())

    def _load_events(company_id: str, ticket_id: str | None = None) -> list[TicketEvent]:
        evts = list(store._events)
        if ticket_id is not None:
            evts = [e for e in evts if e.ticket_id == ticket_id]
        return evts

    async def _save_ticket(ticket: Ticket) -> None:
        store._tickets[ticket.id] = ticket

    async def _append_event(company_id: str, event: TicketEvent) -> None:
        store._events.append(event)

    store.load_tickets.side_effect = _load_tickets
    store.load_events.side_effect = _load_events
    store.save_ticket.side_effect = _save_ticket
    store.append_event.side_effect = _append_event

    return store


def _make_system() -> TicketSystem:
    bus = EventBus()
    store = _make_store()
    return TicketSystem(company_id="test-co", store=store, event_bus=bus)


# ── test_create_ticket ────────────────────────────────────────────────────────


async def test_create_ticket() -> None:
    """create_ticket() returns a Ticket with correct fields and 'open' status."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Fix bug",
        description="Crash on startup",
        assigned_to="code_agent",
        budget_usd=2.0,
    )

    assert ticket.title == "Fix bug"
    assert ticket.description == "Crash on startup"
    assert ticket.assigned_to == "code_agent"
    assert ticket.status == "open"
    assert ticket.budget_usd == 2.0
    assert ticket.company_id == "test-co"
    assert ticket.id  # non-empty UUID string


async def test_create_ticket_appends_created_event() -> None:
    """create_ticket() appends a 'created' event to the audit log."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Deploy", description="Deploy v2", assigned_to="devops_agent"
    )
    events = await ts.get_events(ticket.id)

    assert len(events) >= 1
    assert events[0].event_type == "created"


# ── test_checkout_sets_status ────────────────────────────────────────────────


async def test_checkout_sets_status() -> None:
    """After checkout_ticket(), the ticket status is 'in_progress'."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Task", description="Do something", assigned_to="agent"
    )
    result = await ts.checkout_ticket(ticket.id, "agent")
    assert result is True

    updated = await ts.get_ticket(ticket.id)
    assert updated is not None
    assert updated.status == "in_progress"
    assert updated.started_at is not None


# ── test_checkout_atomic ─────────────────────────────────────────────────────


async def test_checkout_atomic() -> None:
    """Two concurrent checkouts of the same ticket — only one succeeds."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Race", description="Race condition test", assigned_to="agent"
    )

    results = await asyncio.gather(
        ts.checkout_ticket(ticket.id, "agent_a"),
        ts.checkout_ticket(ticket.id, "agent_b"),
    )

    # Exactly one should succeed
    assert results.count(True) == 1
    assert results.count(False) == 1


# ── test_complete_ticket ──────────────────────────────────────────────────────


async def test_complete_ticket() -> None:
    """complete_ticket() sets status to 'done' and adds a completed event."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Ship it", description="Deploy to prod", assigned_to="devops"
    )
    await ts.checkout_ticket(ticket.id, "devops")
    await ts.complete_ticket(ticket.id, "devops", result="Deployed successfully")

    updated = await ts.get_ticket(ticket.id)
    assert updated is not None
    assert updated.status == "done"
    assert updated.completed_at is not None

    events = await ts.get_events(ticket.id)
    event_types = [e.event_type for e in events]
    assert "completed" in event_types


# ── test_fail_ticket_resets ───────────────────────────────────────────────────


async def test_fail_ticket_resets() -> None:
    """fail_ticket() resets status back to 'open' and increments retry_count."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Risky", description="May fail", assigned_to="agent"
    )
    await ts.checkout_ticket(ticket.id, "agent")
    await ts.fail_ticket(ticket.id, "agent", error="timeout")

    updated = await ts.get_ticket(ticket.id)
    assert updated is not None
    assert updated.status == "open"
    assert updated.started_at is None
    assert updated.retry_count == 1


async def test_fail_ticket_adds_failed_event() -> None:
    """fail_ticket() appends a 'failed' event."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Fail me", description="Test failure path", assigned_to="agent"
    )
    await ts.checkout_ticket(ticket.id, "agent")
    await ts.fail_ticket(ticket.id, "agent", error="boom")

    events = await ts.get_events(ticket.id)
    assert any(e.event_type == "failed" for e in events)


# ── test_add_event_immutable ──────────────────────────────────────────────────


async def test_add_event_immutable() -> None:
    """add_event() always appends — calling it N times produces N events."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Audit", description="Test event log", assigned_to="agent"
    )

    initial_count = len(await ts.get_events(ticket.id))

    await ts.add_event(ticket.id, "message", "human", "Note 1")
    await ts.add_event(ticket.id, "message", "human", "Note 2")
    await ts.add_event(ticket.id, "message", "human", "Note 3")

    events = await ts.get_events(ticket.id)
    assert len(events) == initial_count + 3


# ── test_get_events_ordered ───────────────────────────────────────────────────


async def test_get_events_ordered() -> None:
    """Events are returned in creation order (oldest first)."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Order test", description="", assigned_to="agent"
    )
    await ts.add_event(ticket.id, "message", "human", "first")
    await ts.add_event(ticket.id, "message", "human", "second")
    await ts.add_event(ticket.id, "message", "human", "third")

    events = await ts.get_events(ticket.id)
    contents = [e.content for e in events]
    # The "created" event comes first, then our three messages in order
    assert "first" in contents
    assert "second" in contents
    assert "third" in contents
    first_idx = contents.index("first")
    second_idx = contents.index("second")
    third_idx = contents.index("third")
    assert first_idx < second_idx < third_idx


# ── test_sub_ticket ───────────────────────────────────────────────────────────


async def test_sub_ticket() -> None:
    """create_sub_ticket() creates a ticket with parent_ticket_id set."""
    ts = _make_system()
    parent = await ts.create_ticket(
        title="Parent", description="Parent task", assigned_to="agent", budget_usd=4.0
    )
    sub = await ts.create_sub_ticket(
        parent_ticket_id=parent.id,
        title="Sub task",
        description="Child work",
        assigned_to="code_agent",
    )

    assert sub.parent_ticket_id == parent.id
    assert sub.goal_id == parent.goal_id
    assert sub.priority == parent.priority


async def test_sub_ticket_inherits_half_budget() -> None:
    """Sub-ticket gets 50% of the parent's remaining budget when not specified."""
    ts = _make_system()
    parent = await ts.create_ticket(
        title="Parent", description="", assigned_to="agent", budget_usd=4.0
    )
    sub = await ts.create_sub_ticket(
        parent_ticket_id=parent.id,
        title="Sub",
        description="",
        assigned_to="agent",
    )

    # Parent has no costs used, so sub gets 4.0 * 0.5 = 2.0
    assert sub.budget_usd == pytest.approx(2.0)


# ── test_budget_warning_event ─────────────────────────────────────────────────


async def test_budget_warning_event() -> None:
    """update_ticket_cost() at >=80% of budget appends a 'budget_warning' event."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Costly", description="", assigned_to="agent", budget_usd=1.0
    )
    # Record cost that hits 80% threshold
    await ts.update_ticket_cost(ticket.id, 0.85)

    events = await ts.get_events(ticket.id)
    assert any(e.event_type == "budget_warning" for e in events)


async def test_no_budget_warning_below_threshold() -> None:
    """update_ticket_cost() below 80% does NOT emit a budget_warning event."""
    ts = _make_system()
    ticket = await ts.create_ticket(
        title="Cheap", description="", assigned_to="agent", budget_usd=1.0
    )
    await ts.update_ticket_cost(ticket.id, 0.5)

    events = await ts.get_events(ticket.id)
    assert not any(e.event_type == "budget_warning" for e in events)
