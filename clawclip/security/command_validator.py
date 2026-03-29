"""Shell command validation — blocks dangerous patterns before execution."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Regex patterns that are unconditionally blocked.
BLOCKED_PATTERNS: list[str] = [
    r"rm\s+-[^\s]*r[^\s]*f",          # rm -rf / rm -fr variants
    r"rm\s+-[^\s]*f[^\s]*r",
    r":\(\)\s*\{.*\|.*&.*\}",          # fork bomb
    r">\s*/dev/sd[a-z][0-9]*",         # overwrite block device
    r"dd\s+if=.*of=/dev/(?!null|zero)", # dd to real device
    r"mkfs",                            # format filesystem
    r"chmod\s+-R\s+[0-7]*7{2,}\s+/",  # overly-permissive chmod on root
    r"chown\s+-R\s+\w+\s+/[^/]",       # chown -R on root paths
    r"del\s+/[sS]",                     # Windows recursive delete
    r"rd\s+/[sS]",                      # Windows recursive rmdir
    r"format\s+[a-zA-Z]:",             # Windows disk format
    r"bcdedit",                         # Windows boot config
    r"shutdown(?:\s|$)",               # shutdown command
    r"reboot(?:\s|$)",                 # reboot command
    r"halt(?:\s|$)",                   # halt command
    r"init\s+[06]",                    # SysV runlevel 0/6
    r"DROP\s+(?:TABLE|DATABASE)",      # SQL drop
    r"TRUNCATE\s+TABLE",               # SQL truncate
    r"wget\s+.*\|\s*(?:ba)?sh",        # curl/wget pipe to shell
    r"curl\s+.*\|\s*(?:ba)?sh",
]

# Exact command names that are blocked regardless of arguments.
BLOCKED_COMMANDS: list[str] = [
    "format",
    "diskpart",
    "bcdedit",
    "fdisk",
    "parted",
    "mkfs.ext4",
    "mkfs.fat",
    "mkswap",
]

_COMPILED: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE | re.DOTALL) for p in BLOCKED_PATTERNS
]


def validate(command: str) -> tuple[bool, str]:
    """Check a shell command for dangerous patterns.

    Returns (is_safe, reason).  When is_safe is False, reason describes
    which pattern was matched.
    """
    stripped = command.strip()

    # Check exact blocked command names (first token).
    first_token = stripped.split()[0].lower() if stripped else ""
    # Strip path prefix so "/usr/sbin/reboot" still matches "reboot".
    base_cmd = os.path.basename(first_token)
    if base_cmd in BLOCKED_COMMANDS:
        return False, f"Blocked command: {base_cmd!r}"

    # Check regex patterns.
    for pat in _COMPILED:
        match = pat.search(stripped)
        if match:
            return False, f"Blocked pattern matched: {pat.pattern!r}"

    return True, ""


def sanitize_path(path: str, allowed_roots: list[str]) -> str | None:
    """Resolve `path` and return it only if it falls within an allowed root.

    Returns None if the resolved path escapes all allowed roots (path
    traversal guard).
    """
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return None

    for root in allowed_roots:
        try:
            root_resolved = Path(root).resolve()
            resolved.relative_to(root_resolved)
            return str(resolved)
        except ValueError:
            continue

    logger.warning("sanitize_path: %s is outside allowed roots %s", resolved, allowed_roots)
    return None


class CommandValidator:
    """Stateless wrapper around the module-level validate/sanitize_path helpers.

    Provides an object-oriented interface for injection into other components.
    """

    def validate(self, command: str) -> tuple[bool, str]:
        """Delegate to module-level validate()."""
        return validate(command)

    def sanitize_path(self, path: str, allowed_roots: list[str]) -> str | None:
        """Delegate to module-level sanitize_path()."""
        return sanitize_path(path, allowed_roots)
