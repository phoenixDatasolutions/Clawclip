"""Discord output formatter — markdown formatting with Discord-specific escaping."""

from __future__ import annotations

import re


class DiscordFormatter:
    """``OutputFormatter`` implementation for Discord's markdown format.

    Discord uses a CommonMark-like markdown dialect with some extensions.
    Special characters that must be escaped to appear literally:
    ``\\ * _ ` ~ | > # @``
    """

    max_message_length: int = 2000

    # Characters Discord treats as markdown control characters
    _ESCAPE_RE = re.compile(r"([\\*_`~|>#@])")

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
        # Discord renders inline markdown links only in certain contexts,
        # but the syntax is correct per the spec.
        return f"[{text}]({url})"

    def escape(self, text: str) -> str:
        """Escape Discord markdown special characters.

        Prefixes each control character with a backslash so it renders
        as a literal character rather than markdown syntax.
        """
        return self._ESCAPE_RE.sub(r"\\\1", str(text))

    def split_message(self, text: str) -> list[str]:
        """Split a long message into chunks fitting within 2000 characters.

        Tries paragraph, newline, then space boundaries before hard-cutting.
        """
        if len(text) <= self.max_message_length:
            return [text]

        chunks: list[str] = []
        remaining = text
        limit = self.max_message_length

        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            candidate = remaining[:limit]

            # Try paragraph boundary
            pos = candidate.rfind("\n\n", 0, limit)
            if pos > limit // 2:
                split = pos + 2
            else:
                # Try single newline
                pos = candidate.rfind("\n", limit // 2, limit)
                if pos > 0:
                    split = pos + 1
                else:
                    # Try space
                    pos = candidate.rfind(" ", limit // 2, limit)
                    split = pos + 1 if pos > 0 else limit

            chunks.append(remaining[:split])
            remaining = remaining[split:].lstrip("\n")

        return chunks
