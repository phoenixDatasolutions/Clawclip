"""Redis-backed cache with graceful in-memory fallback.

Uses ``redis.asyncio`` (from the ``redis[asyncio]`` package).
Values are JSON-serialised before storage.

If Redis is not installed or the connection fails the cache silently
degrades to :class:`_InMemoryCache`, logging a ``WARNING`` but never
raising an exception to callers.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Optional dependency: redis ────────────────────────────────────

try:
    import redis.asyncio as aioredis
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False


# ── In-memory fallback ────────────────────────────────────────────


class _InMemoryCache:
    """Simple dict-based cache with TTL via :func:`time.monotonic`."""

    def __init__(self) -> None:
        # key -> (value, expiry_monotonic | None)
        self._data: dict[str, tuple[Any, float | None]] = {}

    def _is_expired(self, key: str) -> bool:
        entry = self._data.get(key)
        if entry is None:
            return True
        _, expiry = entry
        if expiry is None:
            return False
        return time.monotonic() > expiry

    def _evict(self, key: str) -> None:
        if self._is_expired(key):
            self._data.pop(key, None)

    async def get(self, key: str) -> Any | None:
        self._evict(key)
        entry = self._data.get(key)
        return entry[0] if entry is not None else None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        expiry = time.monotonic() + ttl if ttl > 0 else None
        self._data[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def exists(self, key: str) -> bool:
        self._evict(key)
        return key in self._data

    async def keys(self, pattern: str = "*") -> list[str]:
        import fnmatch
        # Evict expired entries first
        expired = [k for k in list(self._data) if self._is_expired(k)]
        for k in expired:
            self._data.pop(k, None)
        return [k for k in self._data if fnmatch.fnmatch(k, pattern)]

    async def flush(self) -> None:
        self._data.clear()


# ── Redis cache ───────────────────────────────────────────────────


class RedisCache:
    """Optional Redis cache — falls back to in-memory dict if Redis unavailable.

    Create instances via the async factory :meth:`create` rather than the
    constructor directly, so that the connection attempt (and possible
    fallback) happens at initialisation time.

    Parameters
    ----------
    url:
        Redis connection URL, e.g. ``redis://localhost:6379``.
    """

    def __init__(self) -> None:
        self._redis: Any = None  # aioredis.Redis | None
        self._fallback: _InMemoryCache | None = None

    # ── Factory ───────────────────────────────────────────────────

    @classmethod
    async def create(cls, url: str = "redis://localhost:6379") -> "RedisCache":
        """Create a :class:`RedisCache`, falling back to in-memory if needed.

        Never raises — if Redis is unavailable a warning is logged and an
        in-memory cache is used instead.
        """
        instance = cls()
        if not _HAS_REDIS:
            logger.warning(
                "redis package not installed — using in-memory cache fallback. "
                "Install with: pip install 'redis[asyncio]>=5.0,<6'"
            )
            instance._fallback = _InMemoryCache()
            return instance

        try:
            client = aioredis.from_url(url, decode_responses=True)
            # Verify the connection is live
            await client.ping()
            instance._redis = client
            logger.info("RedisCache connected: %s", url)
        except Exception as exc:
            logger.warning(
                "Redis connection failed (%s) — using in-memory cache fallback.", exc
            )
            instance._fallback = _InMemoryCache()

        return instance

    # ── Internal helpers ──────────────────────────────────────────

    @property
    def _using_fallback(self) -> bool:
        return self._fallback is not None

    def _encode(self, value: Any) -> str:
        return json.dumps(value, default=str)

    def _decode(self, raw: str | None) -> Any | None:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    # ── Public interface ──────────────────────────────────────────

    async def get(self, key: str) -> Any | None:
        """Return the cached value for *key*, or ``None`` if missing/expired."""
        if self._using_fallback:
            return await self._fallback.get(key)  # type: ignore[union-attr]
        try:
            raw = await self._redis.get(key)
            return self._decode(raw)
        except Exception as exc:
            logger.warning("RedisCache.get error: %s", exc)
            return None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Store *value* under *key* with an optional *ttl* in seconds."""
        if self._using_fallback:
            await self._fallback.set(key, value, ttl=ttl)  # type: ignore[union-attr]
            return
        try:
            encoded = self._encode(value)
            if ttl > 0:
                await self._redis.setex(key, ttl, encoded)
            else:
                await self._redis.set(key, encoded)
        except Exception as exc:
            logger.warning("RedisCache.set error: %s", exc)

    async def delete(self, key: str) -> None:
        """Remove *key* from the cache."""
        if self._using_fallback:
            await self._fallback.delete(key)  # type: ignore[union-attr]
            return
        try:
            await self._redis.delete(key)
        except Exception as exc:
            logger.warning("RedisCache.delete error: %s", exc)

    async def exists(self, key: str) -> bool:
        """Return ``True`` if *key* exists and has not expired."""
        if self._using_fallback:
            return await self._fallback.exists(key)  # type: ignore[union-attr]
        try:
            return bool(await self._redis.exists(key))
        except Exception as exc:
            logger.warning("RedisCache.exists error: %s", exc)
            return False

    async def keys(self, pattern: str = "*") -> list[str]:
        """Return all keys matching *pattern* (glob-style)."""
        if self._using_fallback:
            return await self._fallback.keys(pattern)  # type: ignore[union-attr]
        try:
            result = await self._redis.keys(pattern)
            return list(result)
        except Exception as exc:
            logger.warning("RedisCache.keys error: %s", exc)
            return []

    async def flush(self) -> None:
        """Remove all keys from the cache."""
        if self._using_fallback:
            await self._fallback.flush()  # type: ignore[union-attr]
            return
        try:
            await self._redis.flushdb()
        except Exception as exc:
            logger.warning("RedisCache.flush error: %s", exc)
