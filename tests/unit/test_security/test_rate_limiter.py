"""Unit tests for nexusai.security.rate_limiter — RateLimiter and TokenBucket."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from nexusai.security.rate_limiter import RateLimiter, TokenBucket


# ── test_allows_within_limit ──────────────────────────────────────────────────


async def test_allows_within_limit() -> None:
    """10 requests against a 30/min bucket are all allowed."""
    limiter = RateLimiter(requests_per_minute=30)
    results = [await limiter.check("user_a") for _ in range(10)]

    assert all(results), "Expected all 10 requests to be allowed"


# ── test_blocks_at_limit ──────────────────────────────────────────────────────


async def test_blocks_at_limit() -> None:
    """The 31st request in a 30/min bucket is rejected."""
    limiter = RateLimiter(requests_per_minute=30)
    for _ in range(30):
        await limiter.check("user_b")

    result = await limiter.check("user_b")
    assert result is False


# ── test_different_users_independent ─────────────────────────────────────────


async def test_different_users_independent() -> None:
    """User A hitting the rate limit does not affect user B's bucket."""
    limiter = RateLimiter(requests_per_minute=5)

    # Exhaust user_a
    for _ in range(5):
        await limiter.check("user_a")
    blocked = await limiter.check("user_a")
    assert blocked is False

    # user_b still has a fresh bucket
    allowed = await limiter.check("user_b")
    assert allowed is True


# ── test_refill_over_time ─────────────────────────────────────────────────────


async def test_refill_over_time() -> None:
    """After tokens are consumed, advancing time allows more requests."""
    bucket = TokenBucket(capacity=1, refill_rate=10.0)  # 10 tokens/sec

    # Consume the single token
    first = await bucket.consume()
    assert first is True

    second = await bucket.consume()
    assert second is False  # depleted

    # Simulate 1 second of elapsed time by patching time.monotonic
    original_last = bucket._last_refill
    with patch("nexusai.security.rate_limiter.time.monotonic", return_value=original_last + 1.0):
        third = await bucket.consume()

    assert third is True  # refilled


# ── test_reset ────────────────────────────────────────────────────────────────


async def test_reset() -> None:
    """reset() clears a user's bucket back to full capacity."""
    limiter = RateLimiter(requests_per_minute=2)

    # Exhaust the bucket
    await limiter.check("user_c")
    await limiter.check("user_c")
    blocked = await limiter.check("user_c")
    assert blocked is False

    await limiter.reset("user_c")

    # Now should be allowed again
    allowed = await limiter.check("user_c")
    assert allowed is True


# ── test_token_bucket_refill ──────────────────────────────────────────────────


async def test_token_bucket_refill() -> None:
    """TokenBucket._refill() adds the correct number of tokens based on elapsed time."""
    bucket = TokenBucket(capacity=10, refill_rate=5.0)  # 5 tokens/second

    # Drain it completely
    for _ in range(10):
        await bucket.consume()

    assert bucket._tokens < 1.0  # empty (or close to it)

    # Manually advance the internal timestamp by 2 seconds
    bucket._last_refill -= 2.0
    bucket._refill()

    # Should have ~10 tokens added (2s * 5/s = 10), capped at capacity=10
    assert bucket._tokens == pytest.approx(10.0, abs=0.1)


# ── test_reset_unknown_user_no_error ─────────────────────────────────────────


async def test_reset_unknown_user_no_error() -> None:
    """reset() on a user who has no bucket must not raise."""
    limiter = RateLimiter(requests_per_minute=30)
    # Should not raise
    await limiter.reset("user_who_never_sent_anything")


# ── test_token_bucket_capacity_cap ────────────────────────────────────────────


async def test_token_bucket_capacity_cap() -> None:
    """Refilling beyond capacity is capped at the configured max."""
    bucket = TokenBucket(capacity=5, refill_rate=100.0)

    # Manually push last_refill far back — tokens should not exceed capacity
    bucket._last_refill -= 60.0  # 60s * 100/s = 6000 tokens — should cap at 5
    bucket._refill()

    assert bucket._tokens == pytest.approx(5.0)
