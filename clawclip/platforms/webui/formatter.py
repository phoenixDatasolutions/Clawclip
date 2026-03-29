"""WebUI output formatter — markdown output rendered in the browser."""

from __future__ import annotations


class WebUIFormatter:
    """``OutputFormatter`` for the WebUI platform.

    The WebUI renders messages in the browser, so standard CommonMark
    markdown is used verbatim. No server-side escaping is needed — the
    front-end renderer handles sanitisation before injecting into the DOM.
    """

    max_message_length: int = 50_000

    # ── OutputFormatter protocol ──────────────────────────────────

    def bold(self, text: str) -> str:
        return f"**{text}**"

    def italic(self, text: str) -> str:
        return f"*{text}*"

    def code(self, text: str) -> str:
        return f"`{text}`"

    def code_block(self, text: str, language: str = "") -> str:
        lang = language or ""
        return f"```{lang}\n{text}\n```"

    def link(self, text: str, url: str) -> str:
        return f"[{text}]({url})"

    def escape(self, text: str) -> str:
        """No escaping needed — the browser renderer handles sanitisation."""
        return str(text)
