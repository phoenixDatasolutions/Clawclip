"""Slack output formatter — mrkdwn formatting and Block Kit conversion."""

from __future__ import annotations

import re


class SlackFormatter:
    """``OutputFormatter`` implementation for Slack's mrkdwn format.

    Slack uses its own "mrkdwn" dialect rather than standard CommonMark:

    * Bold:       ``*text*``
    * Italic:     ``_text_``
    * Inline code: `` `text` ``
    * Code block: ` ```text``` ` (language tag is ignored)
    * Links:      ``<url|text>``

    The ``to_blocks`` method converts a plain-text / mrkdwn string into
    Slack Block Kit blocks suitable for use with ``chat.postMessage``.
    """

    max_message_length: int = 4000

    # Characters that need escaping in mrkdwn text
    _ESCAPE_RE = re.compile(r"([&<>])")

    # ── OutputFormatter protocol ──────────────────────────────────

    def bold(self, text: str) -> str:
        return f"*{text}*"

    def italic(self, text: str) -> str:
        return f"_{text}_"

    def code(self, text: str) -> str:
        return f"`{text}`"

    def code_block(self, text: str, language: str = "") -> str:
        # Slack ignores the language identifier
        return f"```{text}```"

    def link(self, text: str, url: str) -> str:
        return f"<{url}|{text}>"

    def escape(self, text: str) -> str:
        """Escape Slack mrkdwn HTML entities: ``&``, ``<``, ``>``."""
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    # ── Block Kit ─────────────────────────────────────────────────

    def to_blocks(self, text: str) -> list[dict]:
        """Convert a mrkdwn string into Slack Block Kit block objects.

        The strategy:
        * Fenced code blocks (` ``` ... ``` `) become ``rich_text`` blocks
          with a ``rich_text_preformatted`` element.
        * All other content is split by blank lines into paragraph-sized
          ``section`` blocks (max 3000 chars each per Slack limits).

        Returns a list of Block Kit dicts ready to pass to ``blocks=`` in
        ``chat.postMessage``.
        """
        blocks: list[dict] = []

        # Split on fenced code blocks (``` ... ```)
        parts = re.split(r"(```[\s\S]*?```)", text)

        for part in parts:
            if not part.strip():
                continue

            if part.startswith("```") and part.endswith("```"):
                # Code block: strip the backtick fences
                code_content = part[3:-3].lstrip("\n")
                blocks.append(
                    {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_preformatted",
                                "elements": [
                                    {"type": "text", "text": code_content}
                                ],
                            }
                        ],
                    }
                )
            else:
                # Regular text: split by blank lines into section blocks
                paragraphs = re.split(r"\n{2,}", part.strip())
                for para in paragraphs:
                    if not para.strip():
                        continue
                    # Truncate to Slack's section text limit (3000 chars)
                    chunk = para.strip()[:3000]
                    blocks.append(
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": chunk},
                        }
                    )

        return blocks or [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text[:3000]},
            }
        ]

    def split_message(self, text: str) -> list[str]:
        """Split a long message into chunks fitting within 4000 characters."""
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
            pos = candidate.rfind("\n\n", 0, limit)
            if pos > limit // 2:
                split = pos + 2
            else:
                pos = candidate.rfind("\n", limit // 2, limit)
                if pos > 0:
                    split = pos + 1
                else:
                    pos = candidate.rfind(" ", limit // 2, limit)
                    split = pos + 1 if pos > 0 else limit

            chunks.append(remaining[:split])
            remaining = remaining[split:].lstrip("\n")

        return chunks
