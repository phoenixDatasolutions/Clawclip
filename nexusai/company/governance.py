"""GovernanceManager — policy rules and approval gates for agent actions."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)

MAX_DELEGATION_DEPTH = 5  # hard limit on nested agent calls


class GovernanceRule(str, Enum):
    """Governance rules that restrict what agents may do autonomously."""
    REQUIRE_APPROVAL_FOR_SUB_TICKETS = "require_approval_for_sub_tickets"
    REQUIRE_APPROVAL_FOR_BUDGET_INCREASE = "require_approval_for_budget_increase"
    REQUIRE_APPROVAL_FOR_EXTERNAL_CALLS = "require_approval_for_external_calls"
    MAX_DEPTH_LIMIT = "max_depth_limit"


# Actions that each rule governs
_RULE_ACTIONS: dict[GovernanceRule, set[str]] = {
    GovernanceRule.REQUIRE_APPROVAL_FOR_SUB_TICKETS: {"create_sub_ticket"},
    GovernanceRule.REQUIRE_APPROVAL_FOR_BUDGET_INCREASE: {"increase_budget"},
    GovernanceRule.REQUIRE_APPROVAL_FOR_EXTERNAL_CALLS: {"http_call", "webhook", "external_api"},
    GovernanceRule.MAX_DEPTH_LIMIT: {"delegate"},
}


class GovernanceManager:
    """Enforces governance rules and manages approval workflows.

    Usage::

        gm = GovernanceManager(rules=[GovernanceRule.REQUIRE_APPROVAL_FOR_SUB_TICKETS])
        allowed = await gm.check("create_sub_ticket", actor="code_agent", context={})
        if not allowed:
            approved = await gm.request_approval(...)
    """

    def __init__(
        self,
        rules: list[GovernanceRule] | None = None,
        approval_callback: Callable | None = None,
    ) -> None:
        self._rules: list[GovernanceRule] = rules or []
        self._approval_callback = approval_callback
        # Pending approvals: approval_id → asyncio.Future[bool]
        self._pending: dict[str, asyncio.Future[bool]] = {}

    # ── Rule management ──────────────────────────────────────────

    async def set_rules(self, rules: list[GovernanceRule]) -> None:
        self._rules = list(rules)
        logger.info("GovernanceManager: rules updated to %s", [r.value for r in rules])

    async def get_rules(self) -> list[GovernanceRule]:
        return list(self._rules)

    # ── Checks ────────────────────────────────────────────────────

    async def check(self, action: str, actor: str, context: dict) -> bool:
        """Return True if the action is allowed without approval.

        Checks:
        - MAX_DEPTH_LIMIT: blocks delegation beyond MAX_DELEGATION_DEPTH.
        - Other rules: if the action requires approval, returns False.
        """
        for rule in self._rules:
            governed_actions = _RULE_ACTIONS.get(rule, set())
            if action not in governed_actions:
                continue

            if rule == GovernanceRule.MAX_DEPTH_LIMIT:
                depth = context.get("delegation_depth", 0)
                if depth >= MAX_DELEGATION_DEPTH:
                    logger.warning(
                        "GovernanceManager: action '%s' by '%s' BLOCKED — "
                        "delegation depth %d >= limit %d",
                        action, actor, depth, MAX_DELEGATION_DEPTH,
                    )
                    return False
            else:
                # Approval required — action is not immediately allowed
                logger.info(
                    "GovernanceManager: action '%s' by '%s' requires approval (rule: %s)",
                    action, actor, rule.value,
                )
                return False

        return True

    async def request_approval(
        self, action: str, actor: str, context: dict
    ) -> bool:
        """Block until the action is approved or denied.

        If an ``approval_callback`` was provided it is invoked with the
        approval request details and should eventually call
        ``resolve_approval(approval_id, approved)``.

        If no callback is set, approval is auto-denied.
        """
        import uuid
        approval_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[approval_id] = future

        logger.info(
            "GovernanceManager: approval requested — id=%s action=%s actor=%s",
            approval_id, action, actor,
        )

        if self._approval_callback:
            try:
                await self._approval_callback(
                    approval_id=approval_id,
                    action=action,
                    actor=actor,
                    context=context,
                )
            except Exception:
                logger.exception("GovernanceManager: approval_callback raised an exception")
                self._pending.pop(approval_id, None)
                return False
        else:
            # No callback configured — auto-deny
            logger.warning(
                "GovernanceManager: no approval_callback set; auto-denying %s", approval_id
            )
            future.set_result(False)

        try:
            result = await asyncio.wait_for(future, timeout=300.0)  # 5-minute timeout
        except asyncio.TimeoutError:
            logger.warning("GovernanceManager: approval %s timed out", approval_id)
            result = False
        finally:
            self._pending.pop(approval_id, None)

        return result

    def resolve_approval(self, approval_id: str, approved: bool) -> None:
        """Resolve a pending approval request (called externally).

        Typically invoked by a webhook handler or UI callback after a human
        approves or denies the request.
        """
        future = self._pending.get(approval_id)
        if future and not future.done():
            future.set_result(approved)
            logger.info(
                "GovernanceManager: approval %s resolved → %s",
                approval_id, "approved" if approved else "denied",
            )
        else:
            logger.warning(
                "GovernanceManager: resolve_approval called for unknown/done id %s", approval_id
            )
