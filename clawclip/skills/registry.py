"""Skill Registry — thin wrapper around core Registry for skill instances."""

from __future__ import annotations

import logging
from typing import Any

from clawclip.core.registry import Registry
from clawclip.core.types import ToolDefinition

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Manages registered skill instances and their tool definitions."""

    def __init__(self) -> None:
        self._registry: Registry[Any] = Registry("skills")

    def register(self, skill: Any) -> None:
        self._registry.register(skill.name, skill)

    def get(self, name: str) -> Any | None:
        return self._registry.get(name)

    def list_all(self) -> list[Any]:
        return list(self._registry.list_all().values())

    def names(self) -> list[str]:
        return self._registry.names()

    def has(self, name: str) -> bool:
        return self._registry.has(name)

    def get_all_tool_definitions(self) -> list[ToolDefinition]:
        tools: list[ToolDefinition] = []
        for skill in self.list_all():
            tools.extend(skill.tools)
        return tools

    def __iter__(self):
        return iter(self._registry)

    def __len__(self) -> int:
        return len(self._registry)

    def __repr__(self) -> str:
        return f"SkillRegistry(skills={self._registry.names()})"
