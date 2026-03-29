"""ClawClip Platform Adapters — messaging platform integrations."""

from clawclip.platforms.cli.adapter import CLIAdapter
from clawclip.platforms.discord.adapter import DiscordAdapter
from clawclip.platforms.slack.adapter import SlackAdapter
from clawclip.platforms.telegram.adapter import TelegramAdapter
from clawclip.platforms.webui.adapter import WebUIAdapter

__all__ = [
    "BasePlatformAdapter",
    "CLIAdapter",
    "DiscordAdapter",
    "SlackAdapter",
    "TelegramAdapter",
    "WebUIAdapter",
]
