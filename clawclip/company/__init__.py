"""clawclip.company — Paperclip.ing-inspired company orchestration.

Provides an org-chart-based hierarchy of AI agents, a ticket-based task
system, per-agent budget tracking with throttling, an immutable audit log,
and governance controls.

Public API::

    from clawclip.company import (
        CompanyManager,
        OrgChart,
        TicketSystem,
        GoalManager,
        BudgetManager,
        GovernanceManager,
    )
"""

from __future__ import annotations

from clawclip.company.budgets import BudgetManager
from clawclip.company.goals import GoalManager
from clawclip.company.governance import GovernanceManager, GovernanceRule
from clawclip.company.heartbeat import HeartbeatManager
from clawclip.company.manager import CompanyManager
from clawclip.company.models import (
    Budget,
    Company,
    Goal,
    OrgNode,
    Ticket,
    TicketEvent,
)
from clawclip.company.org_chart import OrgChart, create_default_chart
from clawclip.company.store import CompanyStore
from clawclip.company.tickets import TicketSystem

__all__ = [
    # Top-level facade
    "CompanyManager",
    # Sub-systems
    "OrgChart",
    "TicketSystem",
    "GoalManager",
    "BudgetManager",
    "GovernanceManager",
    "HeartbeatManager",
    # Data models
    "Company",
    "OrgNode",
    "Goal",
    "Ticket",
    "TicketEvent",
    "Budget",
    # Enums / rules
    "GovernanceRule",
    # Factories / utilities
    "create_default_chart",
    "CompanyStore",
]
