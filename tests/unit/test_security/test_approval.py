"""Unit tests for nexusai.security.approval — ApprovalWorkflow."""

from __future__ import annotations

import asyncio

import pytest

from nexusai.security.approval import ApprovalWorkflow, requires_approval


# ── requires_approval tests ───────────────────────────────────────────────────


def test_requires_approval_dangerous() -> None:
    """rm -rf / matches the dangerous pattern and requires approval."""
    assert requires_approval("rm -rf /") is True


def test_requires_approval_rm_fr() -> None:
    """rm -fr variant also triggers approval."""
    assert requires_approval("rm -fr /home") is True


def test_requires_approval_format() -> None:
    """format C: is flagged as dangerous."""
    assert requires_approval("format C:") is True


def test_requires_approval_drop_table() -> None:
    """SQL DROP TABLE requires approval."""
    assert requires_approval("DROP TABLE users") is True


def test_requires_approval_shutdown() -> None:
    """shutdown command requires approval."""
    assert requires_approval("shutdown -h now") is True


def test_safe_command_no_approval() -> None:
    """ls -la is a safe command and does NOT require approval."""
    assert requires_approval("ls -la") is False


def test_echo_safe() -> None:
    """echo hello does not require approval."""
    assert requires_approval("echo hello") is False


def test_git_status_safe() -> None:
    """git status is safe."""
    assert requires_approval("git status") is False


# ── ApprovalWorkflow tests ────────────────────────────────────────────────────


async def test_approve_resolves_wait() -> None:
    """request_approval followed by approve() causes wait_for_approval() to return True."""
    wf = ApprovalWorkflow()
    approval_id = await wf.request_approval(
        action="rm -rf /tmp/test", context={}, requester_id="agent-1"
    )

    # Run approve concurrently with the wait
    async def do_approve() -> None:
        await asyncio.sleep(0)  # yield so wait starts first
        await wf.approve(approval_id, approver_id="admin")

    result, _ = await asyncio.gather(
        wf.wait_for_approval(approval_id, timeout=5.0),
        do_approve(),
    )
    assert result is True


async def test_deny_resolves_wait() -> None:
    """deny() causes wait_for_approval() to return False."""
    wf = ApprovalWorkflow()
    approval_id = await wf.request_approval(
        action="format C:", context={}, requester_id="agent-2"
    )

    async def do_deny() -> None:
        await asyncio.sleep(0)
        await wf.deny(approval_id, approver_id="admin", reason="too dangerous")

    result, _ = await asyncio.gather(
        wf.wait_for_approval(approval_id, timeout=5.0),
        do_deny(),
    )
    assert result is False


async def test_timeout_returns_false() -> None:
    """wait_for_approval returns False when no response arrives within the timeout."""
    wf = ApprovalWorkflow()
    approval_id = await wf.request_approval(
        action="reboot", context={}, requester_id="agent-3"
    )

    result = await wf.wait_for_approval(approval_id, timeout=0.05)
    assert result is False


async def test_get_pending_snapshot() -> None:
    """get_pending() returns the pending requests while they are unresolved."""
    wf = ApprovalWorkflow()
    aid = await wf.request_approval(action="shutdown", context={}, requester_id="u1")

    pending = wf.get_pending()
    assert len(pending) == 1
    assert pending[0]["approval_id"] == aid
    assert pending[0]["action"] == "shutdown"


async def test_approve_unknown_id_no_error() -> None:
    """approve() on an unknown approval_id must not raise."""
    wf = ApprovalWorkflow()
    await wf.approve("does-not-exist", approver_id="admin")  # must not raise


async def test_deny_unknown_id_no_error() -> None:
    """deny() on an unknown approval_id must not raise."""
    wf = ApprovalWorkflow()
    await wf.deny("does-not-exist", approver_id="admin", reason="gone")  # must not raise


async def test_wait_for_unknown_id_returns_false() -> None:
    """wait_for_approval on an unknown id returns False immediately."""
    wf = ApprovalWorkflow()
    result = await wf.wait_for_approval("no-such-id", timeout=5.0)
    assert result is False


async def test_pending_cleared_after_approval() -> None:
    """After wait_for_approval returns, the pending entry is removed."""
    wf = ApprovalWorkflow()
    aid = await wf.request_approval(action="halt", context={}, requester_id="u2")

    async def do_approve() -> None:
        await asyncio.sleep(0)
        await wf.approve(aid, approver_id="admin")

    await asyncio.gather(
        wf.wait_for_approval(aid, timeout=5.0),
        do_approve(),
    )

    assert len(wf.get_pending()) == 0
