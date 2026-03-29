"""Approval workflow for dangerous operations — in-memory, asyncio-native."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

# Regex patterns whose match triggers an approval request.
DANGEROUS_PATTERNS: list[str] = [
    r"rm\s+-rf",
    r"rm\s+-fr",
    r"del\s+/[sS]\s+/[qQ]",
    r"rd\s+/[sS]\s+/[qQ]",
    r"format\s+[a-zA-Z]:",
    r"mkfs",
    r"shutdown",
    r"reboot",
    r"halt",
    r"init\s+0",
    r"init\s+6",
    r">\s*/dev/sd[a-z]",
    r"dd\s+if=.*of=/dev/",
    r"chmod\s+-R\s+777\s+/",
    r"chown\s+-R.*\s+/",
    r":\(\)\s*\{",        # fork bomb
    r"DROP\s+TABLE",
    r"DROP\s+DATABASE",
    r"TRUNCATE\s+TABLE",
]

_COMPILED: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]


def requires_approval(command: str) -> bool:
    """Return True if the command matches any dangerous pattern."""
    return any(pat.search(command) for pat in _COMPILED)


@dataclass
class _PendingApproval:
    approval_id: str
    action: str
    context: dict
    requester_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: bool = False
    approver_id: str = ""
    deny_reason: str = ""


class ApprovalWorkflow:
    """Manages in-memory approval requests for dangerous operations."""

    def __init__(self) -> None:
        self._pending: dict[str, _PendingApproval] = {}
        self._lock = asyncio.Lock()

    async def request_approval(
        self,
        action: str,
        context: dict,
        requester_id: str,
    ) -> str:
        """Create a pending approval and return its ID.

        The caller should then call wait_for_approval(approval_id) to block
        until an admin approves or denies the request.
        """
        approval_id = str(uuid4())
        pending = _PendingApproval(
            approval_id=approval_id,
            action=action,
            context=context,
            requester_id=requester_id,
        )
        async with self._lock:
            self._pending[approval_id] = pending
        logger.info(
            "Approval requested: id=%s action=%r requester=%s",
            approval_id, action, requester_id,
        )
        return approval_id

    async def wait_for_approval(
        self,
        approval_id: str,
        timeout: float = 300.0,
    ) -> bool:
        """Block until the approval is resolved or timeout expires.

        Returns True if approved, False if denied or timed out.
        """
        async with self._lock:
            pending = self._pending.get(approval_id)
        if pending is None:
            logger.warning("wait_for_approval: unknown id %s", approval_id)
            return False

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Approval %s timed out after %.0fs", approval_id, timeout)
            async with self._lock:
                self._pending.pop(approval_id, None)
            return False

        result = pending.approved
        async with self._lock:
            self._pending.pop(approval_id, None)
        return result

    async def approve(self, approval_id: str, approver_id: str) -> None:
        """Approve a pending request."""
        async with self._lock:
            pending = self._pending.get(approval_id)
        if pending is None:
            logger.warning("approve: unknown id %s", approval_id)
            return
        pending.approved = True
        pending.approver_id = approver_id
        pending.event.set()
        logger.info("Approval %s approved by %s", approval_id, approver_id)

    async def deny(
        self,
        approval_id: str,
        approver_id: str,
        reason: str = "",
    ) -> None:
        """Deny a pending request."""
        async with self._lock:
            pending = self._pending.get(approval_id)
        if pending is None:
            logger.warning("deny: unknown id %s", approval_id)
            return
        pending.approved = False
        pending.approver_id = approver_id
        pending.deny_reason = reason
        pending.event.set()
        logger.info("Approval %s denied by %s: %s", approval_id, approver_id, reason)

    def get_pending(self) -> list[dict]:
        """Return a snapshot of all pending approval requests (for admin UI)."""
        return [
            {
                "approval_id": p.approval_id,
                "action": p.action,
                "context": p.context,
                "requester_id": p.requester_id,
                "created_at": p.created_at.isoformat(),
            }
            for p in self._pending.values()
        ]
