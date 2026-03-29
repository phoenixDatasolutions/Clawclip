"""NexusAI Webhooks — outgoing webhook sender with retry and HMAC signing."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time

logger = logging.getLogger(__name__)


class OutgoingWebhookSender:
    """Sends JSON payloads to external URLs via httpx.

    Supports:
    - Plain POST / GET / PUT
    - HMAC-SHA256 request signing when a *secret* is provided
    - Automatic retries with exponential back-off
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret

    # ── public API ────────────────────────────────────────────────

    async def send(
        self,
        url: str,
        payload: dict,
        headers: dict | None = None,
        method: str = "POST",
    ) -> bool:
        """Send *payload* as JSON to *url* using the given HTTP *method*.

        Returns True on success (2xx), False otherwise.
        """
        import httpx

        merged_headers = self._build_headers(payload, headers or {})
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.request(
                    method.upper(),
                    url,
                    json=payload,
                    headers=merged_headers,
                )
                if resp.is_success:
                    logger.debug("Outgoing webhook %s %s -> %d", method, url, resp.status_code)
                    return True
                logger.warning(
                    "Outgoing webhook %s %s returned %d: %s",
                    method,
                    url,
                    resp.status_code,
                    resp.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Outgoing webhook send failed (%s): %s", url, exc)
            return False

    async def send_with_retry(
        self,
        url: str,
        payload: dict,
        headers: dict | None = None,
        method: str = "POST",
        max_retries: int = 3,
    ) -> bool:
        """Send with exponential back-off retries.

        Sleeps 1s, 2s, 4s … between attempts.  Returns True if any attempt
        succeeds, False when all retries are exhausted.
        """
        delay = 1.0
        for attempt in range(1, max_retries + 1):
            ok = await self.send(url, payload, headers=headers, method=method)
            if ok:
                return True
            if attempt < max_retries:
                logger.info(
                    "Retrying outgoing webhook (attempt %d/%d) in %.0fs",
                    attempt,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
        logger.error(
            "Outgoing webhook to %s failed after %d attempt(s)", url, max_retries
        )
        return False

    # ── internal helpers ──────────────────────────────────────────

    def _build_headers(self, payload: dict, extra: dict) -> dict:
        headers = {"Content-Type": "application/json", **extra}
        if self._secret:
            headers["X-NexusAI-Signature"] = self._sign(payload)
        return headers

    def _sign(self, payload: dict) -> str:
        """Compute HMAC-SHA256 signature over the JSON-serialised payload."""
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        sig = hmac.new(
            self._secret.encode(),  # type: ignore[union-attr]
            body,
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={sig}"
