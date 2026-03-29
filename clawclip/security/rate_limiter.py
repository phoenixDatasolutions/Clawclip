"""Token-bucket per-user rate limiter — asyncio-safe."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class TokenBucket:
    """Thread-safe token bucket for rate limiting.

    Tokens refill continuously at `refill_rate` tokens/second up to `capacity`.
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate  # tokens per second
        self._tokens: float = float(capacity)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def consume(self, tokens: int = 1) -> bool:
        """Attempt to consume `tokens` from the bucket.

        Returns True if the tokens were available (request allowed),
        False otherwise (request should be rejected).
        """
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def _refill(self) -> None:
        """Add tokens based on elapsed time (call while holding lock)."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._capacity,
            self._tokens + elapsed * self._refill_rate,
        )
        self._last_refill = now

    async def reset(self) -> None:
        """Refill the bucket to capacity."""
        async with self._lock:
            self._tokens = float(self._capacity)
            self._last_refill = time.monotonic()


class RateLimiter:
    """Per-user rate limiter backed by token buckets.

    Each user gets their own bucket created on first request.
    """

    def __init__(
        self,
        requests_per_minute: int = 30,
        tokens_per_message: int = 1,
    ) -> None:
        self._capacity = requests_per_minute
        self._refill_rate = requests_per_minute / 60.0  # tokens per second
        self._tokens_per_message = tokens_per_message
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()

    def _get_bucket(self, user_id: str) -> TokenBucket:
        """Return (or create) the bucket for user_id. Caller must hold _lock."""
        if user_id not in self._buckets:
            self._buckets[user_id] = TokenBucket(self._capacity, self._refill_rate)
        return self._buckets[user_id]

    async def check(self, user_id: str) -> bool:
        """Return True if the user is within their rate limit.

        Creates a new bucket for the user if one does not exist yet.
        """
        async with self._lock:
            bucket = self._get_bucket(user_id)
        allowed = await bucket.consume(self._tokens_per_message)
        if not allowed:
            logger.debug("Rate limit hit for user %s", user_id)
        return allowed

    async def reset(self, user_id: str) -> None:
        """Reset the rate-limit bucket for user_id (e.g. after an admin action)."""
        async with self._lock:
            bucket = self._buckets.get(user_id)
        if bucket is not None:
            await bucket.reset()
            logger.debug("Rate limit reset for user %s", user_id)
