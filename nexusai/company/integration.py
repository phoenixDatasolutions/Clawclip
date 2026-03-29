"""Company ↔ AgentEngine integration.

Shows how CompanyManager wires into the existing AgentEngine to execute
tickets as agent tasks with full heartbeat, budget, and audit-log support.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from nexusai.company.models import OrgNode, Ticket
from nexusai.core.types import AgentResult, TaskRequest

if TYPE_CHECKING:
    from nexusai.company.manager import CompanyManager

logger = logging.getLogger(__name__)

_HEARTBEAT_PING_INTERVAL = 30.0  # seconds between heartbeat pings during execution


async def execute_ticket_as_agent(
    ticket: Ticket,
    org_node: OrgNode | None,
    company_manager: "CompanyManager",
    agent_engine: Any,
    skill_manager: Any = None,
) -> AgentResult:
    """Execute a ticket through the AgentEngine with full orchestration support.

    Lifecycle:
    1. Governance check (external calls, depth limits).
    2. Build TaskRequest from ticket.
    3. Run agent with concurrent heartbeat pings every 30 s.
    4. Record all LLM/tool events as TicketEvents.
    5. Update ticket budget on completion.

    Args:
        ticket: The ticket to execute.
        org_node: The org chart node describing the agent's role and skills.
        company_manager: The CompanyManager instance for sub-system access.
        agent_engine: The AgentEngine instance.
        skill_manager: Optional SkillManager (attached to engine if omitted).

    Returns:
        AgentResult with success flag, output, and cost.
    """
    company_id = ticket.company_id
    agent_name = org_node.agent_name if org_node else "coordinator"

    # ── Governance pre-check ──────────────────────────────────────
    governance = await company_manager.get_governance(company_id)
    allowed = await governance.check(
        action="execute_ticket",
        actor=agent_name,
        context={"ticket_id": ticket.id, "delegation_depth": 0},
    )
    if not allowed:
        logger.warning(
            "Integration: governance denied execution of ticket %s by '%s'",
            ticket.id, agent_name,
        )
        return AgentResult(
            success=False,
            output=f"Governance denied execution of ticket '{ticket.title}'",
            agent_type=agent_name,
        )

    ticket_system = await company_manager.get_ticket_system(company_id)
    heartbeat_manager = company_manager.get_heartbeat_manager()

    # ── Build TaskRequest ─────────────────────────────────────────
    task = TaskRequest(
        description=_build_task_description(ticket, org_node),
        context={
            "ticket_id": ticket.id,
            "company_id": company_id,
            "goal_id": ticket.goal_id,
            "budget_usd": ticket.budget_usd,
            "tags": ticket.tags,
        },
        priority=ticket.priority,
    )

    await ticket_system.add_event(
        ticket_id=ticket.id,
        event_type="message",
        actor=agent_name,
        content=f"Starting execution via AgentEngine (agent_type={agent_name})",
        data={"task_id": task.task_id},
    )

    # ── Execute with concurrent heartbeat pings ───────────────────
    start_ns = asyncio.get_event_loop().time()
    result: AgentResult

    async def _heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(_HEARTBEAT_PING_INTERVAL)
            try:
                await heartbeat_manager.ping(
                    agent_name=agent_name,
                    company_id=company_id,
                    ticket_id=ticket.id,
                    context={"task_id": task.task_id, "status": "running"},
                )
            except Exception:
                logger.exception("Integration: heartbeat ping failed")

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        # Initial heartbeat
        await heartbeat_manager.ping(
            agent_name=agent_name,
            company_id=company_id,
            ticket_id=ticket.id,
            context={"task_id": task.task_id, "status": "starting"},
        )

        result = await agent_engine.execute_task(task, agent_type=agent_name)

    except Exception as exc:
        logger.exception(
            "Integration: agent execution failed for ticket %s", ticket.id
        )
        result = AgentResult(
            success=False,
            output=str(exc),
            agent_type=agent_name,
        )
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

    elapsed_ms = int((asyncio.get_event_loop().time() - start_ns) * 1000)

    # ── Record result as TicketEvent ──────────────────────────────
    await ticket_system.add_event(
        ticket_id=ticket.id,
        event_type="completed" if result.success else "failed",
        actor=agent_name,
        content=(
            f"Agent '{agent_name}' finished in {elapsed_ms}ms "
            f"(success={result.success}, cost=${result.cost_usd:.4f})"
        ),
        data={
            "success": result.success,
            "output_preview": result.output[:500] if result.output else "",
            "cost_usd": result.cost_usd,
            "duration_ms": elapsed_ms,
        },
    )

    # Record any sub-agent results as events too
    for sub in result.sub_results:
        await ticket_system.add_event(
            ticket_id=ticket.id,
            event_type="message",
            actor=sub.agent_type or "sub_agent",
            content=f"Sub-agent result: {sub.output[:200]}",
            data={
                "agent_type": sub.agent_type,
                "success": sub.success,
                "cost_usd": sub.cost_usd,
            },
        )

    # ── Update budget ─────────────────────────────────────────────
    if result.cost_usd > 0:
        budget_manager = await company_manager.get_budget_manager(company_id)
        await budget_manager.record_cost(agent_name, result.cost_usd, ticket.id)
        await ticket_system.update_ticket_cost(ticket.id, result.cost_usd)

    # Final heartbeat — clear ticket association
    await heartbeat_manager.ping(
        agent_name=agent_name,
        company_id=company_id,
        ticket_id=None,
        context={"status": "idle"},
    )

    return result


def _build_task_description(ticket: Ticket, org_node: OrgNode | None) -> str:
    """Build a detailed task description from a ticket for the AgentEngine."""
    role_context = ""
    if org_node:
        role_context = (
            f"\n\nYou are acting as: {org_node.role_title} ({org_node.agent_name})\n"
            f"Your responsibilities: {org_node.description}\n"
            f"Budget for this task: ${ticket.budget_usd:.2f}"
        )

    goal_context = f"\nTicket goal_id: {ticket.goal_id}" if ticket.goal_id else ""
    tags_context = f"\nTags: {', '.join(ticket.tags)}" if ticket.tags else ""

    return (
        f"{ticket.description}"
        f"{role_context}"
        f"{goal_context}"
        f"{tags_context}"
        f"\n\nTicket ID: {ticket.id}"
    )
