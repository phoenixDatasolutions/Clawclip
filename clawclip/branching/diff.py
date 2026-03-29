"""Branch diff — compare two sets of conversation messages."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _message_key(msg: Any) -> str:
    """Return a stable identity key for a message object or dict."""
    if isinstance(msg, dict):
        return str(msg.get("id") or msg.get("message_id") or "")
    return str(getattr(msg, "id", "") or getattr(msg, "message_id", ""))


def _message_content(msg: Any) -> str:
    """Extract the text content of a message."""
    if isinstance(msg, dict):
        return str(msg.get("content") or msg.get("text") or "")
    return str(getattr(msg, "content", "") or getattr(msg, "text", ""))


async def diff_branches(
    branch_a_messages: list[Any],
    branch_b_messages: list[Any],
) -> dict[str, list[Any]]:
    """Compare two lists of messages and return a simple diff.

    Returns a dict with three keys:
    - ``added``   — messages in B but not in A (by ID)
    - ``removed`` — messages in A but not in B (by ID)
    - ``changed`` — messages present in both but with different content
    """
    a_by_key: dict[str, Any] = {_message_key(m): m for m in branch_a_messages}
    b_by_key: dict[str, Any] = {_message_key(m): m for m in branch_b_messages}

    a_keys = set(a_by_key)
    b_keys = set(b_by_key)

    added = [b_by_key[k] for k in (b_keys - a_keys)]
    removed = [a_by_key[k] for k in (a_keys - b_keys)]
    changed: list[dict[str, Any]] = []

    for key in a_keys & b_keys:
        content_a = _message_content(a_by_key[key])
        content_b = _message_content(b_by_key[key])
        if content_a != content_b:
            changed.append({"key": key, "before": content_a, "after": content_b})

    logger.debug(
        "Branch diff: +%d -%d ~%d", len(added), len(removed), len(changed)
    )
    return {"added": added, "removed": removed, "changed": changed}
