"""NexusAI Built-in Skills — shell, files, git, monitor, screenshot, web search, services."""

from __future__ import annotations

from nexusai.skills.builtin.files import FileSkill
from nexusai.skills.builtin.git import GitSkill
from nexusai.skills.builtin.monitor import SystemMonitorSkill
from nexusai.skills.builtin.screenshot import ScreenshotSkill
from nexusai.skills.builtin.services import ServiceControlSkill
from nexusai.skills.builtin.shell import ShellSkill
from nexusai.skills.builtin.web_search import WebSearchSkill

__all__ = [
    "ShellSkill",
    "GitSkill",
    "FileSkill",
    "SystemMonitorSkill",
    "ScreenshotSkill",
    "WebSearchSkill",
    "ServiceControlSkill",
]
