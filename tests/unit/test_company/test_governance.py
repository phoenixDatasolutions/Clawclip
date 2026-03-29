"""Unit tests for clawclip.company.governance — GovernanceManager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from clawclip.company.governance import (
    MAX_DELEGATION_DEPTH,
    GovernanceManager,
    GovernanceRule,
)


# ── test_allowed_action ───────────────────────────────────────────────────────


async def test_allowed_action() -> None:
    """An action not governed by any rule is immediately allowed."""
    gm = GovernanceManager(rules=[])
    result = await gm.check("some_free_action", actor="agent", context={})
    assert result is True


async def test_allowed_action_not_in_governed_set() -> None:
    """An action that doesn't match the governed actions of any active rule is allowed."""
    gm = GovernanceManager(rules=[GovernanceRule.REQUIRE_APPROVAL_FOR_SUB_TICKETS])
    # "increase_budget" is governed by a DIFFERENT rule not in our list
    result = await gm.check("increase_budget", actor="agent", context={})
    assert result is True


# ── test_blocked_rule_requires_approval ──────────────────────────────────────


async def test_blocked_rule_requires_approval() -> None:
    """When a rule fires for an action, check() returns False."""
    gm = GovernanceManager(
        rules=[GovernanceRule.REQUIRE_APPROVAL_FOR_SUB_TICKETS]
    )
    result = await gm.check("create_sub_ticket", actor="code_agent", context={})
    assert result is False


async def test_external_call_rule_blocks() -> None:
    """REQUIRE_APPROVAL_FOR_EXTERNAL_CALLS blocks http_call action."""
    gm = GovernanceManager(
        rules=[GovernanceRule.REQUIRE_APPROVAL_FOR_EXTERNAL_CALLS]
    )
    result = await gm.check("http_call", actor="agent", context={})
    assert result is False


# ── test_max_depth_hard_limit ─────────────────────────────────────────────────


async def test_max_depth_hard_limit() -> None:
    """delegate action at depth >= MAX_DELEGATION_DEPTH is blocked immediately."""
    gm = GovernanceManager(rules=[GovernanceRule.MAX_DEPTH_LIMIT])
    context = {"delegation_depth": MAX_DELEGATION_DEPTH}  # at the limit

    result = await gm.check("delegate", actor="agent", context=context)
    assert result is False


async def test_below_max_depth_allowed() -> None:
    """delegate action below the depth limit is allowed."""
    gm = GovernanceManager(rules=[GovernanceRule.MAX_DEPTH_LIMIT])
    context = {"delegation_depth": MAX_DELEGATION_DEPTH - 1}

    result = await gm.check("delegate", actor="agent", context=context)
    assert result is True


async def test_max_depth_zero_allowed() -> None:
    """delegate at depth 0 (no nesting) is allowed."""
    gm = GovernanceManager(rules=[GovernanceRule.MAX_DEPTH_LIMIT])
    result = await gm.check("delegate", actor="agent", context={"delegation_depth": 0})
    assert result is True


# ── test_delegate_depth_tracked ───────────────────────────────────────────────


async def test_delegate_depth_tracked() -> None:
    """Depth is read from the context dict; different depths produce different outcomes."""
    gm = GovernanceManager(rules=[GovernanceRule.MAX_DEPTH_LIMIT])

    # One below the limit — allowed
    shallow = await gm.check("delegate", actor="a", context={"delegation_depth": 4})
    # At the limit — blocked
    deep = await gm.check("delegate", actor="a", context={"delegation_depth": 5})

    assert shallow is True
    assert deep is False


# ── test_rules_can_be_updated ────────────────────────────────────────────────


async def test_rules_can_be_updated() -> None:
    """set_rules() replaces the active rule set."""
    gm = GovernanceManager(rules=[])

    # No rules — action is allowed
    r1 = await gm.check("create_sub_ticket", actor="agent", context={})
    assert r1 is True

    # Add a rule — now blocked
    await gm.set_rules([GovernanceRule.REQUIRE_APPROVAL_FOR_SUB_TICKETS])
    r2 = await gm.check("create_sub_ticket", actor="agent", context={})
    assert r2 is False

    # Remove all rules again — allowed again
    await gm.set_rules([])
    r3 = await gm.check("create_sub_ticket", actor="agent", context={})
    assert r3 is True


# ── test_get_rules ────────────────────────────────────────────────────────────


async def test_get_rules() -> None:
    """get_rules() returns the current active rule list."""
    rules = [GovernanceRule.MAX_DEPTH_LIMIT, GovernanceRule.REQUIRE_APPROVAL_FOR_SUB_TICKETS]
    gm = GovernanceManager(rules=rules)

    current = await gm.get_rules()
    assert set(current) == set(rules)


# ── test_request_approval_auto_deny_no_callback ───────────────────────────────


async def test_request_approval_auto_deny_no_callback() -> None:
    """Without an approval_callback, request_approval() auto-denies."""
    gm = GovernanceManager(rules=[])
    result = await gm.request_approval("dangerous_action", actor="agent", context={})
    assert result is False


# ── test_request_approval_resolved_via_callback ───────────────────────────────


async def test_request_approval_resolved_via_callback() -> None:
    """If a callback resolves the approval, request_approval returns its result."""
    gm = GovernanceManager(rules=[])

    async def approving_callback(
        approval_id: str, action: str, actor: str, context: dict
    ) -> None:
        # Immediately resolve as approved
        gm.resolve_approval(approval_id, approved=True)

    gm._approval_callback = approving_callback

    result = await gm.request_approval("safe_action", actor="agent", context={})
    assert result is True


async def test_request_approval_denied_via_callback() -> None:
    """Callback that resolves with False causes request_approval to return False."""
    gm = GovernanceManager(rules=[])

    async def denying_callback(
        approval_id: str, action: str, actor: str, context: dict
    ) -> None:
        gm.resolve_approval(approval_id, approved=False)

    gm._approval_callback = denying_callback

    result = await gm.request_approval("risky", actor="agent", context={})
    assert result is False


# ── test_resolve_approval_unknown_id ─────────────────────────────────────────


def test_resolve_approval_unknown_id_no_error() -> None:
    """resolve_approval() on an unknown ID logs a warning but does not raise."""
    gm = GovernanceManager()
    gm.resolve_approval("no-such-id", approved=True)  # must not raise
