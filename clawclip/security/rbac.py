"""Role-based access control — maps Role enum values to permission sets."""

from __future__ import annotations

import logging
from enum import Enum

from clawclip.core.enums import Role
from clawclip.storage.models.user import User

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """Fine-grained platform permissions."""
    READ_MESSAGES = "read_messages"
    SEND_MESSAGES = "send_messages"
    USE_SHELL = "use_shell"
    USE_FILES = "use_files"
    USE_GIT = "use_git"
    USE_SYSTEM = "use_system"
    MANAGE_USERS = "manage_users"
    ADMIN_PANEL = "admin_panel"
    VIEW_ANALYTICS = "view_analytics"
    MANAGE_AGENTS = "manage_agents"


# Permissions granted to each role.
ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.OWNER: set(Permission),
    Role.USER: {
        Permission.READ_MESSAGES,
        Permission.SEND_MESSAGES,
        Permission.USE_SHELL,
        Permission.USE_FILES,
        Permission.USE_GIT,
    },
    Role.MEMBER: {
        Permission.READ_MESSAGES,
        Permission.SEND_MESSAGES,
        Permission.USE_SHELL,
        Permission.USE_FILES,
        Permission.USE_GIT,
    },
    Role.VIEWER: {
        Permission.READ_MESSAGES,
    },
    Role.READONLY: {
        Permission.READ_MESSAGES,
    },
}

# Skill → minimum permission required to run it.
_SKILL_PERMISSION_MAP: dict[str, Permission] = {
    "shell": Permission.USE_SHELL,
    "files": Permission.USE_FILES,
    "git": Permission.USE_GIT,
    "monitor": Permission.USE_SYSTEM,
    "screenshot": Permission.USE_SYSTEM,
    "users": Permission.MANAGE_USERS,
    "agents": Permission.MANAGE_AGENTS,
}


class RBACManager:
    """Checks whether a user has a permission or can run a skill."""

    def get_user_permissions(self, user: User) -> set[Permission]:
        """Return the full permission set for the user's role."""
        try:
            role = Role(user.role)
        except ValueError:
            logger.warning("Unknown role %r for user %s — defaulting to READONLY", user.role, user.id)
            role = Role.READONLY
        return set(ROLE_PERMISSIONS.get(role, {Permission.READ_MESSAGES}))

    def has_permission(self, user: User, permission: Permission) -> bool:
        """Return True if the user's role grants this permission."""
        return permission in self.get_user_permissions(user)

    def check_skill_access(self, user: User, skill_name: str) -> bool:
        """Return True if the user may run the named skill.

        Skills not in the map are accessible to any authenticated user with
        at least SEND_MESSAGES permission.
        """
        required = _SKILL_PERMISSION_MAP.get(skill_name)
        if required is None:
            return self.has_permission(user, Permission.SEND_MESSAGES)
        return self.has_permission(user, required)
