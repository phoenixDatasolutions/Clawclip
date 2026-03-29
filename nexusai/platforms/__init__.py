"""NexusAI Platform Adapters — messaging platform integrations."""

from nexusai.platforms.cli.adapter import CLIAdapter
from nexusai.platforms.discord.adapter import DiscordAdapter
from nexusai.platforms.slack.adapter import SlackAdapter
from nexusai.platforms.telegram.adapter import TelegramAdapter
from nexusai.platforms.webui.adapter import WebUIAdapter

__all__ = [
    "BasePlatformAdapter",
    "CLIAdapter",
    "DiscordAdapter",
    "SlackAdapter",
    "TelegramAdapter",
    "WebUIAdapter",
]
