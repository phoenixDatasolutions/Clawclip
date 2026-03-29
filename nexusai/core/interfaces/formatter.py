"""Output Formatter protocol — format output for a specific platform."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class OutputFormatter(Protocol):
    """Format output for a specific platform.

    Each platform has different markup: Telegram uses HTML,
    Discord uses Markdown, Slack uses mrkdwn, etc.
    """

    def bold(self, text: str) -> str:
        """Wrap text in bold formatting."""
        ...

    def italic(self, text: str) -> str:
        """Wrap text in italic formatting."""
        ...

    def code(self, text: str) -> str:
        """Wrap text in inline code formatting."""
        ...

    def code_block(self, text: str, language: str = "") -> str:
        """Wrap text in a code block with optional language."""
        ...

    def link(self, text: str, url: str) -> str:
        """Create a hyperlink."""
        ...

    def escape(self, text: str) -> str:
        """Escape special characters for this platform."""
        ...

    def max_message_length(self) -> int:
        """Maximum message length for this platform."""
        ...

    def split_message(self, text: str) -> list[str]:
        """Split a long message into chunks that fit the platform limit."""
        ...
