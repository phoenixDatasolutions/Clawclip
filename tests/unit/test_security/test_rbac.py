"""Unit tests for nexusai.security.rbac — RBACManager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nexusai.core.enums import Role
from nexusai.security.rbac import Permission, RBACManager


# ── Helpers ───────────────────────────────────────────────────────────────────


def _user(role: str) -> MagicMock:
    """Create a minimal mock User with just a .role attribute."""
    user = MagicMock()
    user.role = role
    user.id = f"user-{role}"
    return user


# ── test_admin_has_all_permissions ────────────────────────────────────────────


def test_admin_has_all_permissions() -> None:
    """Admin role is granted every Permission value."""
    rbac = RBACManager()
    admin = _user(Role.ADMIN)
    perms = rbac.get_user_permissions(admin)

    for permission in Permission:
        assert permission in perms, f"Admin missing {permission}"


# ── test_owner_has_all_permissions ────────────────────────────────────────────


def test_owner_has_all_permissions() -> None:
    """Owner role also gets the full permission set."""
    rbac = RBACManager()
    owner = _user(Role.OWNER)
    perms = rbac.get_user_permissions(owner)

    for permission in Permission:
        assert permission in perms, f"Owner missing {permission}"


# ── test_user_has_basic_permissions ──────────────────────────────────────────


def test_user_has_basic_permissions() -> None:
    """Regular USER role has messaging, shell, files, and git permissions."""
    rbac = RBACManager()
    user = _user(Role.USER)

    assert rbac.has_permission(user, Permission.READ_MESSAGES)
    assert rbac.has_permission(user, Permission.SEND_MESSAGES)
    assert rbac.has_permission(user, Permission.USE_SHELL)
    assert rbac.has_permission(user, Permission.USE_FILES)
    assert rbac.has_permission(user, Permission.USE_GIT)


# ── test_user_lacks_admin_permissions ────────────────────────────────────────


def test_user_lacks_admin_permissions() -> None:
    """Regular USER must not have admin-only permissions."""
    rbac = RBACManager()
    user = _user(Role.USER)

    assert not rbac.has_permission(user, Permission.MANAGE_USERS)
    assert not rbac.has_permission(user, Permission.ADMIN_PANEL)


# ── test_readonly_limited ─────────────────────────────────────────────────────


def test_readonly_limited() -> None:
    """READONLY role cannot execute shell or access files."""
    rbac = RBACManager()
    readonly = _user(Role.READONLY)

    assert rbac.has_permission(readonly, Permission.READ_MESSAGES)
    assert not rbac.has_permission(readonly, Permission.USE_SHELL)
    assert not rbac.has_permission(readonly, Permission.USE_FILES)
    assert not rbac.has_permission(readonly, Permission.SEND_MESSAGES)


# ── test_viewer_limited ───────────────────────────────────────────────────────


def test_viewer_limited() -> None:
    """VIEWER role only has READ_MESSAGES."""
    rbac = RBACManager()
    viewer = _user(Role.VIEWER)

    assert rbac.has_permission(viewer, Permission.READ_MESSAGES)
    assert not rbac.has_permission(viewer, Permission.SEND_MESSAGES)
    assert not rbac.has_permission(viewer, Permission.USE_SHELL)


# ── test_skill_access_shell ───────────────────────────────────────────────────


def test_skill_access_shell() -> None:
    """A USER (with USE_SHELL) can access the shell skill."""
    rbac = RBACManager()
    user = _user(Role.USER)

    assert rbac.check_skill_access(user, "shell") is True


# ── test_skill_access_denied ──────────────────────────────────────────────────


def test_skill_access_denied() -> None:
    """READONLY user is denied the shell skill."""
    rbac = RBACManager()
    readonly = _user(Role.READONLY)

    assert rbac.check_skill_access(readonly, "shell") is False


# ── test_check_tool_permission_files ─────────────────────────────────────────


def test_check_tool_permission_files() -> None:
    """A USER can access the files skill; READONLY cannot."""
    rbac = RBACManager()
    user = _user(Role.USER)
    readonly = _user(Role.READONLY)

    assert rbac.check_skill_access(user, "files") is True
    assert rbac.check_skill_access(readonly, "files") is False


# ── test_skill_not_in_map_requires_send_messages ──────────────────────────────


def test_skill_not_in_map_requires_send_messages() -> None:
    """Skills not in the permission map require only SEND_MESSAGES."""
    rbac = RBACManager()
    user = _user(Role.USER)       # has SEND_MESSAGES
    readonly = _user(Role.READONLY)  # does NOT have SEND_MESSAGES

    assert rbac.check_skill_access(user, "some_unlisted_skill") is True
    assert rbac.check_skill_access(readonly, "some_unlisted_skill") is False


# ── test_unknown_role_defaults_to_readonly ────────────────────────────────────


def test_unknown_role_defaults_to_readonly() -> None:
    """An unknown role string falls back to READ_MESSAGES only."""
    rbac = RBACManager()
    mystery = _user("superuser_hacker")

    perms = rbac.get_user_permissions(mystery)
    assert Permission.READ_MESSAGES in perms
    assert Permission.USE_SHELL not in perms


# ── test_member_same_as_user ──────────────────────────────────────────────────


def test_member_same_as_user() -> None:
    """MEMBER role has the same permissions as USER."""
    rbac = RBACManager()
    member = _user(Role.MEMBER)

    assert rbac.has_permission(member, Permission.USE_SHELL)
    assert rbac.has_permission(member, Permission.USE_FILES)
    assert rbac.has_permission(member, Permission.USE_GIT)
    assert not rbac.has_permission(member, Permission.ADMIN_PANEL)
