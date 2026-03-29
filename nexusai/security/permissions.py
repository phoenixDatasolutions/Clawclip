"""Permission matrix — maps skills and tools to required permission strings."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Skill-level permission requirements.  Values are Permission enum value strings.
SKILL_PERMISSIONS: dict[str, list[str]] = {
    "shell": ["USE_SHELL"],
    "files": ["USE_FILES"],
    "git": ["USE_GIT"],
    "monitor": ["USE_SYSTEM"],
    "screenshot": ["USE_SYSTEM"],
    "users": ["MANAGE_USERS"],
    "agents": ["MANAGE_AGENTS"],
    "analytics": ["VIEW_ANALYTICS"],
    "admin": ["ADMIN_PANEL"],
}

# Tool-level permission requirements (more granular than skill level).
TOOL_PERMISSIONS: dict[str, list[str]] = {
    # Shell tools
    "run_command": ["USE_SHELL"],
    "run_script": ["USE_SHELL"],
    # File tools
    "read_file": ["USE_FILES"],
    "write_file": ["USE_FILES"],
    "delete_file": ["USE_FILES"],
    "list_directory": ["USE_FILES"],
    # Git tools
    "git_status": ["USE_GIT"],
    "git_commit": ["USE_GIT"],
    "git_push": ["USE_GIT"],
    "git_clone": ["USE_GIT"],
    # System tools
    "get_processes": ["USE_SYSTEM"],
    "kill_process": ["USE_SYSTEM"],
    "take_screenshot": ["USE_SYSTEM"],
    "get_system_info": ["USE_SYSTEM"],
    # Admin tools
    "list_users": ["MANAGE_USERS"],
    "update_user_role": ["MANAGE_USERS"],
    "ban_user": ["MANAGE_USERS"],
    "manage_agent": ["MANAGE_AGENTS"],
    "view_analytics": ["VIEW_ANALYTICS"],
    "admin_panel": ["ADMIN_PANEL"],
}

# Role hierarchy: higher index = more permissions.
_ROLE_RANK: dict[str, int] = {
    "readonly": 0,
    "viewer": 0,
    "member": 1,
    "user": 1,
    "admin": 2,
    "owner": 2,
}

# Minimum role rank required for each permission.
_PERMISSION_MIN_RANK: dict[str, int] = {
    "READ_MESSAGES": 0,
    "SEND_MESSAGES": 1,
    "USE_SHELL": 1,
    "USE_FILES": 1,
    "USE_GIT": 1,
    "USE_SYSTEM": 1,
    "VIEW_ANALYTICS": 1,
    "MANAGE_USERS": 2,
    "ADMIN_PANEL": 2,
    "MANAGE_AGENTS": 2,
}


def check_tool_permission(user_role: str, skill: str, tool: str) -> bool:
    """Return True if user_role satisfies the permissions required for (skill, tool).

    Resolution order: tool-level requirements first, then skill-level.
    An unknown tool/skill defaults to requiring at least the USER role rank.
    """
    role_rank = _ROLE_RANK.get(user_role.lower(), -1)
    if role_rank < 0:
        logger.warning("Unknown role %r — denying access", user_role)
        return False

    # Collect all required permission strings.
    required: list[str] = []
    if tool in TOOL_PERMISSIONS:
        required.extend(TOOL_PERMISSIONS[tool])
    elif skill in SKILL_PERMISSIONS:
        required.extend(SKILL_PERMISSIONS[skill])
    else:
        # Unknown tool/skill — require at least USER rank.
        required = ["SEND_MESSAGES"]

    for perm in required:
        min_rank = _PERMISSION_MIN_RANK.get(perm, 1)
        if role_rank < min_rank:
            return False
    return True
