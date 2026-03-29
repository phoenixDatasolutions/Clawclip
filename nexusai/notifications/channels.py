"""NexusAI Notifications — delivery channel implementations."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from nexusai.core.enums import NotificationSeverity

logger = logging.getLogger(__name__)


# ── Protocol ──────────────────────────────────────────────────────────────────


@runtime_checkable
class NotificationChannel(Protocol):
    """Interface every notification channel must satisfy."""

    name: str

    async def send(self, message: str, severity: NotificationSeverity) -> bool:
        """Deliver *message* on this channel.

        Returns True on success, False on failure.  Implementations must never
        raise — all errors should be caught and logged internally.
        """
        ...


# ── Telegram ──────────────────────────────────────────────────────────────────


class TelegramNotificationChannel:
    """Sends notifications via the Telegram Bot API."""

    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id

    async def send(self, message: str, severity: NotificationSeverity) -> bool:
        try:
            import httpx

            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            payload = {
                "chat_id": self._chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            logger.debug("Telegram notification sent (severity=%s)", severity)
            return True
        except Exception as exc:
            logger.error("TelegramNotificationChannel.send failed: %s", exc)
            return False


# ── Webhook ───────────────────────────────────────────────────────────────────


class WebhookNotificationChannel:
    """POSTs a JSON notification payload to an arbitrary URL."""

    name = "webhook"

    def __init__(self, url: str, headers: dict | None = None) -> None:
        self._url = url
        self._headers: dict = headers or {}

    async def send(self, message: str, severity: NotificationSeverity) -> bool:
        try:
            import httpx

            payload = {"message": message, "severity": severity.value}
            merged_headers = {"Content-Type": "application/json", **self._headers}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._url, json=payload, headers=merged_headers)
                resp.raise_for_status()
            logger.debug("Webhook notification sent to %s (severity=%s)", self._url, severity)
            return True
        except Exception as exc:
            logger.error("WebhookNotificationChannel.send failed (%s): %s", self._url, exc)
            return False


# ── Log ───────────────────────────────────────────────────────────────────────

_SEVERITY_TO_LOG_LEVEL: dict[NotificationSeverity, int] = {
    NotificationSeverity.INFO: logging.INFO,
    NotificationSeverity.WARNING: logging.WARNING,
    NotificationSeverity.CRITICAL: logging.CRITICAL,
}


class LogNotificationChannel:
    """Writes notifications to the Python logging system.

    Always available — useful as a fallback or during development.
    """

    name = "log"

    def __init__(self, logger_name: str = "nexusai.notifications") -> None:
        self._logger = logging.getLogger(logger_name)

    async def send(self, message: str, severity: NotificationSeverity) -> bool:
        level = _SEVERITY_TO_LOG_LEVEL.get(severity, logging.INFO)
        self._logger.log(level, "[Notification] %s", message)
        return True
