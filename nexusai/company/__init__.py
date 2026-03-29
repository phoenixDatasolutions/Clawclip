"""nexusai.company — Paperclip.ing-inspired company orchestration.

Provides an org-chart-based hierarchy of AI agents, a ticket-based task
system, per-agent budget tracking with throttling, an immutable audit log,
and governance controls.

Public API::

    from nexusai.company import (
        CompanyManager,
        OrgChart,
        TicketSystem,
        GoalManager,
        BudgetManager,
        GovernanceManager,
    )
"""

from __future__ import annotations

from nexusai.company.budgets import BudgetManager
from nexusai.company.goals import GoalManager
from nexusai.company.governance import GovernanceManager, GovernanceRule
from nexusai.company.heartbeat import HeartbeatManager
from nexusai.company.manager import CompanyManager
from nexusai.company.models import (
    Budget,
    Company,
    Goal,
    OrgNode,
    Ticket,
    TicketEvent,
)
from nexusai.company.org_chart import OrgChart, create_default_chart
from nexusai.company.store import CompanyStore
from nexusai.company.tickets import TicketSystem

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
