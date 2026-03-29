"""ClawClip Skills — modular plugin system for agent capabilities."""

from __future__ import annotations

from clawclip.skills.loader import SkillLoader
from clawclip.skills.manager import SkillManager
from clawclip.skills.registry import SkillRegistry

__all__ = [
    "SkillManager",
    "SkillLoader",
    "SkillRegistry",
]
