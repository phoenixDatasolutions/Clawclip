"""Skill Loader — auto-discover and dynamically load skill modules."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillLoader:
    """Discover and instantiate skill objects from builtin and developer packages."""

    _BUILTIN_MODULES = [
        "clawclip.skills.builtin.shell",
        "clawclip.skills.builtin.git",
        "clawclip.skills.builtin.files",
        "clawclip.skills.builtin.monitor",
        "clawclip.skills.builtin.screenshot",
        "clawclip.skills.builtin.web_search",
        "clawclip.skills.builtin.services",
        "clawclip.skills.builtin.browser",
    ]

    _DEVELOPER_MODULES = [
        "clawclip.skills.developer.code_review",
        "clawclip.skills.developer.pr_management",
        "clawclip.skills.developer.ci_cd",
        "clawclip.skills.developer.deployment",
        "clawclip.skills.developer.log_analysis",
        "clawclip.skills.developer.db_ops",
        "clawclip.skills.developer.api_testing",
        "clawclip.skills.developer.qa",
        "clawclip.skills.developer.automation",
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config: dict[str, Any] = config or {}

    def discover_builtin_skills(self) -> list[Any]:
        return self._load_modules(self._BUILTIN_MODULES)

    def discover_developer_skills(self) -> list[Any]:
        return self._load_modules(self._DEVELOPER_MODULES)

    def load_from_directory(self, path: str) -> list[Any]:
        """Dynamically import all Python modules in a directory and call create_skill()."""
        dir_path = Path(path)
        if not dir_path.is_dir():
            logger.warning("Skill directory not found: %s", path)
            return []

        skills: list[Any] = []
        for py_file in sorted(dir_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = f"_clawclip_dynamic.{py_file.stem}"
            skill = self._load_from_file(py_file, module_name)
            if skill is not None:
                skills.append(skill)

        logger.info("Loaded %d skill(s) from %s", len(skills), path)
        return skills

    # ── private helpers ──────────────────────────────────────────

    def _load_modules(self, module_names: list[str]) -> list[Any]:
        skills: list[Any] = []
        for module_name in module_names:
            skill = self._load_module(module_name)
            if skill is not None:
                skills.append(skill)
        return skills

    def _load_module(self, module_name: str) -> Any | None:
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            logger.warning("Could not import skill module %s: %s", module_name, e)
            return None

        if not hasattr(module, "create_skill"):
            logger.warning("Skill module %s has no create_skill() factory", module_name)
            return None

        skill_config = self._config.get(module_name.split(".")[-1], {})
        try:
            skill = module.create_skill(skill_config)
            logger.debug("Loaded skill '%s' from %s", skill.name, module_name)
            return skill
        except Exception as e:
            logger.error("Failed to instantiate skill from %s: %s", module_name, e)
            return None

    def _load_from_file(self, py_file: Path, module_name: str) -> Any | None:
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning("Failed to load skill file %s: %s", py_file, e)
            return None

        if not hasattr(module, "create_skill"):
            logger.debug("Skill file %s has no create_skill() factory, skipping", py_file.name)
            return None

        try:
            skill = module.create_skill({})
            logger.debug("Loaded skill '%s' from file %s", skill.name, py_file)
            return skill
        except Exception as e:
            logger.error("Failed to instantiate skill from %s: %s", py_file, e)
            return None
