"""Team role hierarchy and per-role permission sets for workspaces."""

from __future__ import annotations

from enum import Enum


class TeamRole(str, Enum):
    """Roles a user can hold within a workspace."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


# Permissions each team role grants within a workspace.
TEAM_ROLE_PERMISSIONS: dict[TeamRole, set[str]] = {
    TeamRole.OWNER: {
        "manage_workspace",
        "invite_members",
        "remove_members",
        "change_roles",
        "delete_workspace",
        "view_analytics",
        "share_conversations",
        "share_knowledge_base",
        "run_agents",
        "view_conversations",
    },
    TeamRole.ADMIN: {
        "manage_workspace",
        "invite_members",
        "remove_members",
        "change_roles",
        "view_analytics",
        "share_conversations",
        "share_knowledge_base",
        "run_agents",
        "view_conversations",
    },
    TeamRole.MEMBER: {
        "invite_members",
        "share_conversations",
        "run_agents",
        "view_conversations",
    },
    TeamRole.VIEWER: {
        "view_conversations",
    },
}

# Roles that have at least one management permission.
_MANAGEMENT_ROLES = {TeamRole.OWNER, TeamRole.ADMIN}
_INVITE_ROLES = {TeamRole.OWNER, TeamRole.ADMIN, TeamRole.MEMBER}
_ANALYTICS_ROLES = {TeamRole.OWNER, TeamRole.ADMIN}


def can_manage_workspace(role: TeamRole) -> bool:
    """Return True if the role may modify workspace settings or members."""
    return role in _MANAGEMENT_ROLES


def can_invite_members(role: TeamRole) -> bool:
    """Return True if the role may invite new members."""
    return role in _INVITE_ROLES


def can_view_analytics(role: TeamRole) -> bool:
    """Return True if the role may access workspace analytics."""
    return role in _ANALYTICS_ROLES
