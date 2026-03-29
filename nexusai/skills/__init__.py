"""NexusAI Skills — modular plugin system for agent capabilities."""

from __future__ import annotations

from nexusai.skills.loader import SkillLoader
from nexusai.skills.manager import SkillManager
from nexusai.skills.registry import SkillRegistry

__all__ = [
    "SkillManager",
    "SkillLoader",
    "SkillRegistry",
]
