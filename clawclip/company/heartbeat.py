"""AgentHeartbeat — liveness tracking and abandoned-ticket recovery."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawclip.company.store import CompanyStore

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 30.0      # seconds between background sweeps
_DEFAULT_TIMEOUT = 120.0        # seconds before a ticket is considered abandoned


@dataclass
class HeartbeatRecord:
    """Snapshot of an agent's last known state."""
    agent_name: str
    company_id: str
    ticket_id: str | None
    last_seen: datetime
    context: dict = field(default_factory=dict)


class HeartbeatManager:
    """Publishes and monitors agent heartbeats to detect crashed/stalled agents.

    The background task runs every ``_HEARTBEAT_INTERVAL`` seconds and calls
    ``get_abandoned_tickets``.  Any abandoned ticket is re-opened for retry;
    a "resumed" event is appended to the audit log.
    """

    def __init__(self, store: "CompanyStore") -> None:
        self._store = store
        self._background_task: asyncio.Task | None = None

    # ── Ping ─────────────────────────────────────────────────────

    async def ping(
        self,
        agent_name: str,
        company_id: str,
        ticket_id: str | None,
        context: dict | None = None,
    ) -> None:
        """Record a heartbeat for an agent."""
        record = {
            "agent_name": agent_name,
            "company_id": company_id,
            "ticket_id": ticket_id,
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "context": context or {},
        }
        await self._store.save_heartbeat(record)

    async def get_heartbeat(self, agent_name: str) -> HeartbeatRecord | None:
        """Return the most recent heartbeat for an agent across all companies.

        Searches all companies in the store.
        """
        from pathlib import Path
        from clawclip.company.store import _DATA_ROOT

        if not _DATA_ROOT.exists():
            return None

        for company_dir in _DATA_ROOT.iterdir():
            if not company_dir.is_dir():
                continue
            heartbeats = self._store.load_heartbeats(company_dir.name)
            for h in heartbeats:
                if h.get("agent_name") == agent_name:
                    last_seen_raw = h.get("last_seen")
                    last_seen: datetime
                    if isinstance(last_seen_raw, str):
                        try:
                            last_seen = datetime.fromisoformat(last_seen_raw)
                            if last_seen.tzinfo is None:
                                last_seen = last_seen.replace(tzinfo=timezone.utc)
                        except ValueError:
                            last_seen = datetime.now(timezone.utc)
                    else:
                        last_seen = datetime.now(timezone.utc)
                    return HeartbeatRecord(
                        agent_name=h["agent_name"],
                        company_id=h["company_id"],
                        ticket_id=h.get("ticket_id"),
                        last_seen=last_seen,
                        context=h.get("context", {}),
                    )
        return None

    # ── Abandoned ticket detection ────────────────────────────────

    async def get_abandoned_tickets(
        self,
        timeout_seconds: float = _DEFAULT_TIMEOUT,
    ) -> list[str]:
        """Return ticket_ids whose assigned agent hasn't pinged recently.

        An agent is considered abandoned if ``now - last_seen > timeout_seconds``
        and the agent is currently assigned to a ticket in "in_progress" status.
        """
        from pathlib import Path
        from clawclip.company.store import _DATA_ROOT

        if not _DATA_ROOT.exists():
            return []

        now = datetime.now(timezone.utc)
        abandoned: list[str] = []

        for company_dir in _DATA_ROOT.iterdir():
            if not company_dir.is_dir():
                continue
            company_id = company_dir.name
            heartbeats = {
                h["agent_name"]: h
                for h in self._store.load_heartbeats(company_id)
            }
            tickets = self._store.load_tickets(company_id)

            for ticket in tickets:
                if ticket.status != "in_progress":
                    continue

                # Find the heartbeat for the assigned agent
                assigned_agent = ticket.assigned_to
                hb = heartbeats.get(assigned_agent)
                if hb is None:
                    # No heartbeat at all — abandoned
                    abandoned.append(ticket.id)
                    continue

                last_seen_raw = hb.get("last_seen")
                if isinstance(last_seen_raw, str):
                    try:
                        last_seen = datetime.fromisoformat(last_seen_raw)
                        if last_seen.tzinfo is None:
                            last_seen = last_seen.replace(tzinfo=timezone.utc)
                    except ValueError:
                        abandoned.append(ticket.id)
                        continue
                else:
                    abandoned.append(ticket.id)
                    continue

                elapsed = (now - last_seen).total_seconds()
                if elapsed > timeout_seconds:
                    logger.warning(
                        "HeartbeatManager: ticket %s abandoned — agent '%s' last seen %.0fs ago",
                        ticket.id, assigned_agent, elapsed,
                    )
                    abandoned.append(ticket.id)

        return abandoned

    async def resume_ticket(self, ticket_id: str, new_agent: str) -> None:
        """Re-assign an abandoned ticket to a new agent and log the event.

        Resets the ticket to "open" so it can be checked out again.
        """
        from pathlib import Path
        from clawclip.company.store import _DATA_ROOT

        if not _DATA_ROOT.exists():
            return

        for company_dir in _DATA_ROOT.iterdir():
            if not company_dir.is_dir():
                continue
            company_id = company_dir.name
            tickets = {t.id: t for t in self._store.load_tickets(company_id)}
            ticket = tickets.get(ticket_id)
            if ticket is None:
                continue

            old_agent = ticket.assigned_to
            ticket.status = "open"
            ticket.assigned_to = new_agent
            ticket.started_at = None
            await self._store.save_ticket(ticket)

            # Append resume event to audit log
            from clawclip.company.models import TicketEvent
            from uuid import uuid4

            event = TicketEvent(
                id=str(uuid4()),
                ticket_id=ticket_id,
                event_type="resumed",
                actor="heartbeat_manager",
                content=(
                    f"Ticket re-assigned from abandoned agent '{old_agent}' "
                    f"to '{new_agent}'"
                ),
                data={"old_agent": old_agent, "new_agent": new_agent},
                created_at=datetime.now(timezone.utc),
            )
            await self._store.append_event(company_id, event)
            logger.info(
                "HeartbeatManager: ticket %s resumed — new agent '%s'", ticket_id, new_agent
            )
            return

    # ── Background sweep ──────────────────────────────────────────

    def start_background_task(self) -> None:
        """Start the periodic abandoned-ticket sweep."""
        if self._background_task is None or self._background_task.done():
            self._background_task = asyncio.create_task(self._sweep_loop())
            logger.info("HeartbeatManager: background sweep started")

    def stop_background_task(self) -> None:
        """Stop the background sweep."""
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            logger.info("HeartbeatManager: background sweep stopped")

    async def _sweep_loop(self) -> None:
        """Periodically find abandoned tickets and reset them for retry."""
        while True:
            try:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                abandoned = await self.get_abandoned_tickets()
                for ticket_id in abandoned:
                    # Re-open for retry — no specific agent, let the scheduler pick it up
                    await self.resume_ticket(ticket_id, new_agent="coordinator")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("HeartbeatManager: error in sweep loop")
