"""NexusAI Configuration — YAML loader with environment variable interpolation and hot-reload."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _interpolate_env_vars(value: Any) -> Any:
    """Recursively replace ${VAR} and ${VAR:default} patterns with environment values."""
    if isinstance(value, str):
        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            default = match.group(2)
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val
            if default is not None:
                return default
            return match.group(0)  # Leave as-is if not found and no default

        return _ENV_VAR_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env_vars(item) for item in value]
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge override into base. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class NexusConfig:
    """Configuration manager with YAML loading, env var interpolation, and hot-reload.

    Loads config/default.yaml as the base, then merges config/local.yaml on top.
    Environment variables can override any value using ${VAR_NAME} syntax.
    """

    def __init__(self, config_dir: str | Path = "config") -> None:
        self._config_dir = Path(config_dir)
        self._data: dict[str, Any] = {}
        self._watchers: list[Any] = []

    def load(self) -> None:
        """Load configuration from YAML files."""
        default_path = self._config_dir / "default.yaml"
        local_path = self._config_dir / "local.yaml"

        # Load default config (shipped with the project)
        if default_path.exists():
            with open(default_path, encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
            logger.info("Loaded default config from %s", default_path)
        else:
            logger.warning("No default.yaml found at %s", default_path)
            self._data = {}

        # Merge local config (user's choices, git-ignored)
        if local_path.exists():
            with open(local_path, encoding="utf-8") as f:
                local_data = yaml.safe_load(f) or {}
            self._data = _deep_merge(self._data, local_data)
            logger.info("Merged local config from %s", local_path)

        # Interpolate environment variables
        self._data = _interpolate_env_vars(self._data)

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get a config value by dot-separated path.

        Example: config.get("platforms.telegram.bot_token")
        """
        keys = key_path.split(".")
        value = self._data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path: str, value: Any) -> None:
        """Set a config value by dot-separated path (in-memory only)."""
        keys = key_path.split(".")
        data = self._data
        for key in keys[:-1]:
            if key not in data or not isinstance(data[key], dict):
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value

    def is_enabled(self, feature_path: str) -> bool:
        """Check if a feature is enabled. Convenience for config.get("features.X.enabled")."""
        return bool(self.get(f"{feature_path}.enabled", False))

    def save_local(self, overrides: dict[str, Any] | None = None) -> None:
        """Save current overrides to config/local.yaml."""
        local_path = self._config_dir / "local.yaml"
        data = overrides if overrides is not None else self._data
        with open(local_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        logger.info("Saved local config to %s", local_path)

    def reload(self) -> dict[str, Any]:
        """Reload configuration and return changed keys.

        Returns a dict of {key_path: new_value} for changed values.
        """
        old_data = self._data.copy()
        self.load()
        changes = self._diff(old_data, self._data)
        if changes:
            logger.info("Config reloaded with %d changes", len(changes))
        return changes

    @property
    def data(self) -> dict[str, Any]:
        """Raw config data dict."""
        return self._data

    def _diff(
        self,
        old: dict[str, Any],
        new: dict[str, Any],
        prefix: str = "",
    ) -> dict[str, Any]:
        """Find changed keys between old and new config."""
        changes: dict[str, Any] = {}
        all_keys = set(old.keys()) | set(new.keys())
        for key in all_keys:
            full_key = f"{prefix}.{key}" if prefix else key
            old_val = old.get(key)
            new_val = new.get(key)
            if isinstance(old_val, dict) and isinstance(new_val, dict):
                changes.update(self._diff(old_val, new_val, full_key))
            elif old_val != new_val:
                changes[full_key] = new_val
        return changes
