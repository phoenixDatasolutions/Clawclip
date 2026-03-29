"""Agent Loader — load AgentConfig definitions from YAML files."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from clawclip.core.types import AgentConfig

logger = logging.getLogger(__name__)


class AgentLoader:
    """Loads :class:`~clawclip.core.types.AgentConfig` objects from YAML files.

    YAML format example::

        name: code_agent
        description: "Handles code generation, review, and debugging"
        provider: claude-api
        model: claude-opus-4-6
        allowed_skills: [shell, files, git]
        system_prompt: "You are a code specialist..."
        max_turns: 20
        temperature: 0.3

    The ``name`` field is mapped to ``agent_type`` in :class:`AgentConfig`.
    All other fields map directly; unknown keys are stored in ``extra``.
    """

    # Known fields and their AgentConfig kwarg names + defaults
    _KNOWN_FIELDS: dict[str, tuple[str, Any]] = {
        "name":           ("agent_type",     ""),
        "provider":       ("provider",       "claude-api"),
        "model":          ("model",          "claude-opus-4-6"),
        "system_prompt":  ("system_prompt",  ""),
        "allowed_skills": ("allowed_skills", None),  # None → replace with []
        "max_turns":      ("max_turns",      50),
        "temperature":    ("temperature",    0.7),
        "max_tokens":     ("max_tokens",     4096),
        "max_delegations":("max_delegations",5),
    }

    def load_from_yaml(self, path: str) -> AgentConfig:
        """Load a single :class:`AgentConfig` from a YAML file.

        Args:
            path: Absolute or relative path to the YAML file.

        Returns:
            A fully populated :class:`AgentConfig` instance.

        Raises:
            FileNotFoundError: If *path* does not exist.
            ValueError: If required fields (``name``, ``provider``, ``model``) are missing.
        """
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to load agent definitions. "
                "Install it with: pip install pyyaml"
            ) from exc

        resolved = Path(path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Agent config file not found: {path}")

        with resolved.open("r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        return self._dict_to_config(raw, source=str(resolved))

    def load_all_agents(self, config_dir: str) -> list[AgentConfig]:
        """Load all YAML files from *config_dir* as :class:`AgentConfig` objects.

        Non-YAML files and files that fail to parse are skipped with a warning.

        Args:
            config_dir: Path to the directory containing agent YAML files.

        Returns:
            List of successfully loaded :class:`AgentConfig` objects, sorted by
            ``agent_type`` for deterministic ordering.
        """
        config_path = Path(config_dir).resolve()
        if not config_path.is_dir():
            logger.warning("AgentLoader: config_dir '%s' does not exist or is not a directory", config_dir)
            return []

        configs: list[AgentConfig] = []
        for entry in sorted(config_path.iterdir()):
            if entry.suffix not in {".yaml", ".yml"} or not entry.is_file():
                continue
            try:
                cfg = self.load_from_yaml(str(entry))
                configs.append(cfg)
                logger.debug("AgentLoader: loaded '%s' from %s", cfg.agent_type, entry.name)
            except Exception as exc:
                logger.warning("AgentLoader: skipping '%s' — %s", entry.name, exc)

        logger.info("AgentLoader: loaded %d agent config(s) from %s", len(configs), config_dir)
        return configs

    # ── Internal helpers ─────────────────────────────────────────

    def _dict_to_config(self, raw: dict[str, Any], source: str = "") -> AgentConfig:
        """Convert a raw YAML dict to an :class:`AgentConfig`."""
        # Validate required fields
        for required in ("name",):
            if not raw.get(required):
                raise ValueError(
                    f"Agent config from '{source}' is missing required field '{required}'."
                )

        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}

        for key, value in raw.items():
            if key in self._KNOWN_FIELDS:
                kwarg_name, default = self._KNOWN_FIELDS[key]
                # Replace None default for allowed_skills with empty list
                if kwarg_name == "allowed_skills" and value is None:
                    value = []
                kwargs[kwarg_name] = value
            elif key == "description":
                # Store description in extra; AgentConfig doesn't have it directly
                extra["description"] = value
            else:
                extra[key] = value

        # Apply defaults for any missing known fields
        for field_name, (kwarg_name, default) in self._KNOWN_FIELDS.items():
            if kwarg_name not in kwargs:
                kwargs[kwarg_name] = [] if default is None else default

        kwargs["extra"] = extra

        return AgentConfig(**kwargs)
