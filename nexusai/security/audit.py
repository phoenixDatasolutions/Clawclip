"""AuditLogger — subscribes to EventBus and writes security events to CommandLog."""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from nexusai.core.events import (
    AuthFailure,
    Event,
    EventBus,
    RateLimitHit,
    SkillExecuted,
)
from nexusai.storage.models.command_log import CommandLog

logger = logging.getLogger(__name__)


class AuditLogger:
    """Persists security-relevant events to the CommandLog table.

    Usage::

        audit = AuditLogger(event_bus, session_factory)
        await audit.start()
        # ... application runs ...
        await audit.stop()
    """

    def __init__(self, event_bus: EventBus, db_session_factory: Callable[[], Any]) -> None:
        self._bus = event_bus
        self._session_factory = db_session_factory
        self._started = False

    async def start(self) -> None:
        """Subscribe to relevant events on the EventBus."""
        if self._started:
            return
        self._bus.subscribe(SkillExecuted, self._log_skill_executed)
        self._bus.subscribe(AuthFailure, self._log_auth_failure)
        self._bus.subscribe(RateLimitHit, self._log_rate_limit_hit)
        self._started = True
        logger.info("AuditLogger started")

    async def stop(self) -> None:
        """Unsubscribe from the EventBus."""
        self._bus.unsubscribe(SkillExecuted, self._log_skill_executed)
        self._bus.unsubscribe(AuthFailure, self._log_auth_failure)
        self._bus.unsubscribe(RateLimitHit, self._log_rate_limit_hit)
        self._started = False
        logger.info("AuditLogger stopped")

    # ── Handlers ────────────────────────────────────────────────

    async def _log_skill_executed(self, event: SkillExecuted) -> None:  # type: ignore[override]
        """Write a CommandLog entry when a skill runs."""
        await self._write_log(
            user_id=event.user_id or "unknown",
            platform="internal",
            command_type="skill",
            command_text=f"{event.skill_name}.{event.tool_name}",
            agent_id=event.agent_id or None,
            skill_name=event.skill_name,
            duration_ms=event.duration_ms,
            status="success" if event.success else "error",
        )

    async def _log_auth_failure(self, event: AuthFailure) -> None:  # type: ignore[override]
        """Write a CommandLog entry for authentication failures."""
        await self._write_log(
            user_id="anonymous",
            platform=event.platform,
            command_type="auth_failure",
            command_text=f"platform_user_id={event.platform_user_id}",
            status="error",
            error_message=event.reason,
        )

    async def _log_rate_limit_hit(self, event: RateLimitHit) -> None:  # type: ignore[override]
        """Write a CommandLog entry when a user exceeds their rate limit."""
        await self._write_log(
            user_id=event.user_id,
            platform=event.platform,
            command_type="rate_limit",
            command_text=f"limit_type={event.limit_type}",
            status="blocked",
        )

    # ── Internal ─────────────────────────────────────────────────

    async def _write_log(self, **kwargs: Any) -> None:
        """Persist a CommandLog row using the session factory."""
        try:
            async with self._session_factory() as session:
                session.add(CommandLog(**kwargs))
                await session.commit()
        except Exception:
            logger.exception("AuditLogger: failed to write log entry")
