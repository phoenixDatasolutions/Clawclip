"""Split long text into Telegram-safe chunks respecting code blocks."""

from __future__ import annotations

MAX_LENGTH = 4000  # Leave margin below Telegram's 4096 limit


def split_text(text: str, max_length: int = MAX_LENGTH) -> list[str]:
    """Split text into chunks that fit within Telegram message limits.

    Respects code block boundaries (```) and prefers splitting at newlines.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Find a good split point
        split_at = _find_split_point(remaining, max_length)
        chunk = remaining[:split_at]
        remaining = remaining[split_at:]

        # Handle code block continuity
        open_blocks = chunk.count("```")
        if open_blocks % 2 != 0:
            # Unclosed code block — close it in this chunk, reopen in next
            chunk += "\n```"
            remaining = "```\n" + remaining

        chunks.append(chunk)

    return chunks


def _find_split_point(text: str, max_length: int) -> int:
    """Find the best position to split text at or before max_length."""
    # Try splitting at a double newline (paragraph boundary)
    pos = text.rfind("\n\n", 0, max_length)
    if pos > max_length // 2:
        return pos + 2

    # Try splitting at a single newline
    pos = text.rfind("\n", 0, max_length)
    if pos > max_length // 3:
        return pos + 1

    # Try splitting at a space
    pos = text.rfind(" ", 0, max_length)
    if pos > max_length // 3:
        return pos + 1

    # Hard cut
    return max_length
