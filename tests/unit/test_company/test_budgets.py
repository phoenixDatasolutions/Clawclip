"""Unit tests for nexusai.company.budgets — BudgetManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexusai.company.budgets import BudgetManager
from nexusai.company.models import Budget, Ticket


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_store(initial_budget: Budget | None = None) -> MagicMock:
    """Return a mock CompanyStore that holds one Budget in memory."""
    store = MagicMock()
    _state: dict[str, Budget] = {}

    if initial_budget is not None:
        _state[initial_budget.company_id] = initial_budget

    def _load_budget(company_id: str) -> Budget | None:
        return _state.get(company_id)

    async def _save_budget(budget: Budget) -> None:
        _state[budget.company_id] = budget

    store.load_budget.side_effect = _load_budget
    store.save_budget = AsyncMock(side_effect=_save_budget)

    # load_tickets not needed for most tests — default to empty
    store.load_tickets.return_value = []

    store._state = _state  # expose for test introspection
    return store


def _make_manager(
    company_id: str = "co1",
    initial_budget: Budget | None = None,
) -> tuple[BudgetManager, MagicMock]:
    store = _make_store(initial_budget)
    mgr = BudgetManager(company_id=company_id, store=store)
    return mgr, store


# ── test_record_cost_accumulates ──────────────────────────────────────────────


async def test_record_cost_accumulates() -> None:
    """Two record_cost(0.5) calls → used_usd == 1.0."""
    mgr, store = _make_manager("co1")

    await mgr.record_cost("agent_a", 0.5)
    await mgr.record_cost("agent_a", 0.5)

    budget = await mgr.get_budget("co1")
    assert budget.used_usd == pytest.approx(1.0)
    assert budget.agent_used.get("agent_a") == pytest.approx(1.0)


# ── test_throttle_at_limit ────────────────────────────────────────────────────


async def test_throttle_at_limit() -> None:
    """Recording cost equal to the agent's limit throttles that agent."""
    budget = Budget(
        company_id="co2",
        period="monthly",
        limit_usd=100.0,
        agent_budgets={"bot": 5.0},
    )
    mgr, store = _make_manager("co2", initial_budget=budget)

    await mgr.record_cost("bot", 5.0)

    assert await mgr.is_throttled("bot") is True


# ── test_is_throttled ─────────────────────────────────────────────────────────


async def test_is_throttled() -> None:
    """is_throttled() returns True after an agent exceeds their limit."""
    budget = Budget(
        company_id="co3",
        period="daily",
        limit_usd=50.0,
        agent_budgets={"worker": 2.0},
    )
    mgr, _ = _make_manager("co3", initial_budget=budget)

    await mgr.record_cost("worker", 3.0)  # exceeds limit
    assert await mgr.is_throttled("worker") is True


# ── test_not_throttled_below_limit ────────────────────────────────────────────


async def test_not_throttled_below_limit() -> None:
    """is_throttled() returns False while an agent is under their limit."""
    budget = Budget(
        company_id="co4",
        period="monthly",
        limit_usd=100.0,
        agent_budgets={"runner": 10.0},
    )
    mgr, _ = _make_manager("co4", initial_budget=budget)

    await mgr.record_cost("runner", 1.0)
    assert await mgr.is_throttled("runner") is False


# ── test_80_percent_warning ───────────────────────────────────────────────────


async def test_80_percent_warning(caplog) -> None:
    """At 80% usage a warning is logged (but agent is NOT yet throttled)."""
    import logging

    budget = Budget(
        company_id="co5",
        period="monthly",
        limit_usd=100.0,
        agent_budgets={"analyst": 10.0},
    )
    mgr, _ = _make_manager("co5", initial_budget=budget)

    with caplog.at_level(logging.WARNING, logger="nexusai.company.budgets"):
        await mgr.record_cost("analyst", 8.0)  # exactly 80%

    assert await mgr.is_throttled("analyst") is False
    # A warning was emitted
    assert any("warning" in record.message.lower() or "80" in record.message for record in caplog.records)


# ── test_period_reset ─────────────────────────────────────────────────────────


async def test_period_reset() -> None:
    """reset_period() zeroes out used_usd and clears throttled_agents."""
    budget = Budget(
        company_id="co6",
        period="monthly",
        limit_usd=100.0,
        agent_budgets={"bot": 1.0},
        used_usd=50.0,
        agent_used={"bot": 2.0},
        throttled_agents={"bot"},
    )
    mgr, _ = _make_manager("co6", initial_budget=budget)

    await mgr.reset_period("monthly")

    refreshed = await mgr.get_budget("co6")
    assert refreshed.used_usd == 0.0
    assert refreshed.agent_used == {}
    assert len(refreshed.throttled_agents) == 0


async def test_period_reset_wrong_period_no_op() -> None:
    """reset_period() with a period that doesn't match the budget does nothing."""
    budget = Budget(
        company_id="co7",
        period="monthly",
        limit_usd=100.0,
        used_usd=30.0,
    )
    mgr, _ = _make_manager("co7", initial_budget=budget)

    await mgr.reset_period("daily")  # wrong period

    refreshed = await mgr.get_budget("co7")
    assert refreshed.used_usd == pytest.approx(30.0)


# ── test_agent_budget_status ──────────────────────────────────────────────────


async def test_agent_budget_status() -> None:
    """get_agent_budget_status() returns correct remaining/percentage fields."""
    budget = Budget(
        company_id="co8",
        period="monthly",
        limit_usd=100.0,
        agent_budgets={"coder": 20.0},
        agent_used={"coder": 5.0},
    )
    mgr, _ = _make_manager("co8", initial_budget=budget)

    status = await mgr.get_agent_budget_status("coder")

    assert status["limit"] == pytest.approx(20.0)
    assert status["used"] == pytest.approx(5.0)
    assert status["remaining"] == pytest.approx(15.0)
    assert status["percentage"] == pytest.approx(0.25)
    assert status["throttled"] is False


async def test_agent_budget_status_no_limit() -> None:
    """get_agent_budget_status() handles agents with no configured limit."""
    budget = Budget(company_id="co9", period="monthly", limit_usd=100.0)
    mgr, _ = _make_manager("co9", initial_budget=budget)

    status = await mgr.get_agent_budget_status("unknown_agent")
    assert status["limit"] is None
    assert status["remaining"] is None
    assert status["percentage"] is None
    assert status["used"] == pytest.approx(0.0)


# ── test_company_budget_status ────────────────────────────────────────────────


async def test_company_budget_status() -> None:
    """get_company_budget_status() returns complete summary dict."""
    budget = Budget(
        company_id="co10",
        period="monthly",
        limit_usd=100.0,
        used_usd=25.0,
        agent_budgets={"agent_x": 30.0},
        agent_used={"agent_x": 10.0},
    )
    mgr, _ = _make_manager("co10", initial_budget=budget)

    summary = await mgr.get_company_budget_status()

    assert summary["company_id"] == "co10"
    assert summary["limit_usd"] == pytest.approx(100.0)
    assert summary["used_usd"] == pytest.approx(25.0)
    assert summary["remaining_usd"] == pytest.approx(75.0)
    assert summary["percentage"] == pytest.approx(0.25)
    assert "agent_x" in summary["agents"]


# ── test_check_ticket_budget ──────────────────────────────────────────────────


async def test_check_ticket_budget_allowed() -> None:
    """check_ticket_budget() returns True when agent is not throttled and ticket has budget."""
    from datetime import datetime, timezone

    budget = Budget(company_id="co11", period="monthly", limit_usd=100.0)
    ticket = Ticket(
        id="t1",
        company_id="co11",
        goal_id=None,
        title="Work",
        description="",
        assigned_to="bot",
        status="open",
        budget_usd=5.0,
        cost_used_usd=1.0,
        created_at=datetime.now(timezone.utc),
    )
    store = _make_store(initial_budget=budget)
    store.load_tickets.return_value = [ticket]
    mgr = BudgetManager(company_id="co11", store=store)

    result = await mgr.check_ticket_budget("t1", "bot")
    assert result is True


async def test_check_ticket_budget_denied_throttled() -> None:
    """check_ticket_budget() returns False when agent is throttled."""
    from datetime import datetime, timezone

    budget = Budget(
        company_id="co12",
        period="monthly",
        limit_usd=100.0,
        agent_budgets={"bot": 1.0},
        agent_used={"bot": 2.0},
        throttled_agents={"bot"},
    )
    ticket = Ticket(
        id="t2",
        company_id="co12",
        goal_id=None,
        title="Work",
        description="",
        assigned_to="bot",
        status="open",
        budget_usd=5.0,
        cost_used_usd=0.0,
        created_at=datetime.now(timezone.utc),
    )
    store = _make_store(initial_budget=budget)
    store.load_tickets.return_value = [ticket]
    mgr = BudgetManager(company_id="co12", store=store)

    result = await mgr.check_ticket_budget("t2", "bot")
    assert result is False
