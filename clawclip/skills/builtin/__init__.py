"""ClawClip Built-in Skills — shell, files, git, monitor, screenshot, web search, services, browser."""

from __future__ import annotations

from clawclip.skills.builtin.browser import BrowserSkill
from clawclip.skills.builtin.files import FileSkill
from clawclip.skills.builtin.git import GitSkill
from clawclip.skills.builtin.monitor import SystemMonitorSkill
from clawclip.skills.builtin.screenshot import ScreenshotSkill
from clawclip.skills.builtin.services import ServiceControlSkill
from clawclip.skills.builtin.shell import ShellSkill
from clawclip.skills.builtin.web_search import WebSearchSkill

__all__ = [
    "BrowserSkill",
    "ShellSkill",
    "GitSkill",
    "FileSkill",
    "SystemMonitorSkill",
    "ScreenshotSkill",
    "WebSearchSkill",
    "ServiceControlSkill",
]
