"""Path validation and command safety checks.

This is the canonical location for security helpers within ClawClip.
A compatibility copy also lives at clawclip.utils.security.
"""

from __future__ import annotations

from pathlib import Path

from clawclip.core.config import NexusConfig

# Shell commands that should never run from the bot
BLOCKED_COMMANDS = {
    "format",
    "diskpart",
    "bcdedit",
    "shutdown /s",
    "shutdown /r",
    "del /s /q C:",
    "rd /s /q C:",
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    ":(){:|:&};:",
}

# Module-level config — loaded lazily on first use
_config: NexusConfig | None = None


def _get_config() -> NexusConfig:
    """Return the module-level NexusConfig, loading it if needed."""
    global _config
    if _config is None:
        _config = NexusConfig()
        _config.load()
    return _config


def set_config(config: NexusConfig) -> None:
    """Allow callers to inject a pre-loaded config instance."""
    global _config
    _config = config


def validate_path(path_str: str) -> Path:
    """Resolve a path and ensure it's within allowed roots.

    Raises ValueError if path is outside allowed roots or contains traversal.
    """
    cfg = _get_config()
    allowed_roots: list[str] = cfg.get(
        "security.allowed_roots",
        ["D:\\Projects", "C:\\Users\\DESKTOP"],
    )

    resolved = Path(path_str).resolve()
    for root in allowed_roots:
        root_resolved = Path(root).resolve()
        try:
            resolved.relative_to(root_resolved)
            return resolved
        except ValueError:
            continue
    raise ValueError(f"Path {resolved} is outside allowed roots: {allowed_roots}")


def is_sensitive_file(filename: str) -> bool:
    """Check if a filename matches blocked patterns."""
    cfg = _get_config()
    blocked_patterns: list[str] = cfg.get(
        "security.blocked_file_patterns",
        [".env", "credentials", ".key", "id_rsa", ".pem"],
    )

    lower = filename.lower()
    return any(pattern.lower() in lower for pattern in blocked_patterns)


def validate_shell_command(command: str) -> str | None:
    """Return a warning message if the command looks dangerous, else None."""
    lower = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if blocked.lower() in lower:
            return f"Blocked: command contains '{blocked}'"
    return None
