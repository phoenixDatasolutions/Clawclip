"""ClawClip Webhooks — generic JSON webhook parser."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def parse_generic_webhook(headers: dict, payload: dict) -> dict:
    """Wrap an arbitrary JSON payload in the normalized event envelope.

    This parser never returns None — any valid JSON body is accepted and
    wrapped verbatim.  Use it as a catch-all for services that don't have a
    dedicated parser.
    """
    return {
        "event_type": "webhook",
        "data": payload,
    }
