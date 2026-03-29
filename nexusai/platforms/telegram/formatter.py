"""Telegram output formatter — HTML formatting with safe escaping and message splitting."""

from __future__ import annotations

import html
import re


class TelegramFormatter:
    """``OutputFormatter`` implementation for Telegram's HTML parse mode.

    Telegram supports a subset of HTML: ``<b>``, ``<i>``, ``<code>``,
    ``<pre>``, ``<a href>``, ``<s>``, ``<u>``, ``<tg-spoiler>``.
    All other entities must be HTML-escaped.
    """

    MAX_LENGTH = 4096

    # ── OutputFormatter protocol ──────────────────────────────────

    def bold(self, text: str) -> str:
        return f"<b>{self.escape(text)}</b>"

    def italic(self, text: str) -> str:
        return f"<i>{self.escape(text)}</i>"

    def code(self, text: str) -> str:
        return f"<code>{self.escape(text)}</code>"

    def code_block(self, text: str, language: str = "") -> str:
        escaped = self.escape(text)
        if language:
            return f'<pre><code class="language-{self.escape(language)}">{escaped}</code></pre>'
        return f"<pre><code>{escaped}</code></pre>"

    def link(self, text: str, url: str) -> str:
        return f'<a href="{self.escape(url)}">{self.escape(text)}</a>'

    def escape(self, text: str) -> str:
        """Escape HTML special characters: ``&``, ``<``, ``>``, ``"``.

        Uses the stdlib ``html.escape`` which covers exactly the characters
        Telegram requires to be escaped.
        """
        return html.escape(str(text), quote=True)

    def max_message_length(self) -> int:
        return self.MAX_LENGTH

    def split_message(self, text: str) -> list[str]:
        """Split a long message into chunks that fit within Telegram's 4096 limit.

        The splitter tries to find a clean break point in this priority order:
        1. Close an open ``<pre>`` / ``<code>`` block at the boundary
        2. Split at a paragraph break (double newline)
        3. Split at a single newline
        4. Split at a space
        5. Hard-split at ``MAX_LENGTH``

        Open code blocks are re-opened in the next chunk so formatting
        is preserved across splits.
        """
        if len(text) <= self.MAX_LENGTH:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= self.MAX_LENGTH:
                chunks.append(remaining)
                break

            # Determine if we're inside a code block at the split point
            candidate = remaining[: self.MAX_LENGTH]

            # Try splitting at a clean boundary
            split_pos = self._find_split_point(candidate)

            chunk = remaining[:split_pos]
            remaining = remaining[split_pos:].lstrip("\n")

            # Repair unclosed tags
            chunk, prefix = self._repair_code_blocks(chunk)
            if prefix:
                remaining = prefix + remaining

            chunks.append(chunk)

        return chunks

    # ── Internal helpers ──────────────────────────────────────────

    def _find_split_point(self, candidate: str) -> int:
        """Find the best split point within a candidate chunk."""
        max_len = self.MAX_LENGTH

        # 1. Try splitting at a paragraph boundary (double newline)
        pos = candidate.rfind("\n\n", 0, max_len)
        if pos > max_len // 2:
            return pos + 2

        # 2. Try splitting at a single newline
        pos = candidate.rfind("\n", max_len // 2, max_len)
        if pos > 0:
            return pos + 1

        # 3. Try splitting at a space
        pos = candidate.rfind(" ", max_len // 2, max_len)
        if pos > 0:
            return pos + 1

        # 4. Hard split
        return max_len

    def _repair_code_blocks(self, chunk: str) -> tuple[str, str]:
        """Close unclosed ``<pre>`` or ``<code>`` tags and return a re-opener prefix.

        Returns:
            (repaired_chunk, prefix_for_next_chunk)
        """
        # Count open/close tags
        open_pre = len(re.findall(r"<pre>", chunk, re.IGNORECASE))
        close_pre = len(re.findall(r"</pre>", chunk, re.IGNORECASE))
        open_code = len(re.findall(r"<code[^>]*>", chunk, re.IGNORECASE))
        close_code = len(re.findall(r"</code>", chunk, re.IGNORECASE))

        prefix = ""
        suffix = ""

        # If there's an unclosed <code> inside a <pre>, close both
        if open_pre > close_pre and open_code > close_code:
            suffix = "</code></pre>"
            # Extract the opening <code> tag to replicate class attribute
            code_match = re.search(r"(<code[^>]*>)", chunk, re.IGNORECASE)
            code_tag = code_match.group(1) if code_match else "<code>"
            prefix = f"<pre>{code_tag}"
        elif open_pre > close_pre:
            suffix = "</pre>"
            prefix = "<pre>"
        elif open_code > close_code:
            suffix = "</code>"
            code_match = re.search(r"(<code[^>]*>)", chunk, re.IGNORECASE)
            code_tag = code_match.group(1) if code_match else "<code>"
            prefix = code_tag

        return chunk + suffix, prefix
