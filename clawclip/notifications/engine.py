"""ClawClip Notifications — central notification dispatch engine."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from clawclip.core.enums import NotificationSeverity
from clawclip.core.events import (
    AgentTaskCompleted,
    EventBus,
    WorkflowCompleted,
)
from clawclip.notifications.channels import LogNotificationChannel, NotificationChannel
from clawclip.notifications.rules import RulesEngine

logger = logging.getLogger(__name__)


class NotificationEngine:
    """Subscribes to the EventBus and dispatches notifications via channels.

    Features
    --------
    - Rule-based routing: events are matched to channels via RulesEngine.
    - Direct send: callers can push a message to specific channels by name.
    - Digest mode: when *digest_interval_seconds* > 0, notifications are
      buffered and flushed as a batch summary instead of being sent immediately.
    """

    def __init__(
        self,
        channels: dict[str, NotificationChannel] | None = None,
        rules: RulesEngine | None = None,
        event_bus: EventBus | None = None,
        digest_interval_seconds: int = 0,
    ) -> None:
        # Always ensure at least a log channel is available.
        self._channels: dict[str, NotificationChannel] = {
            "log": LogNotificationChannel(),
        }
        if channels:
            self._channels.update(channels)

        self._rules = rules or RulesEngine()
        self._event_bus = event_bus
        self._digest_interval = digest_interval_seconds
        self._digest_buffer: list[tuple[str, NotificationSeverity]] = []
        self._digest_task: asyncio.Task[None] | None = None
        self._running = False

    # ── lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to relevant EventBus events and start the digest loop."""
        self._running = True

        if self._event_bus is not None:
            self._event_bus.subscribe(AgentTaskCompleted, self._handle_agent_completed)
            self._event_bus.subscribe(WorkflowCompleted, self._handle_workflow_completed)
            self._event_bus.subscribe_all(self._handle_any_event)

        if self._digest_interval > 0:
            self._digest_task = asyncio.create_task(self._digest_loop())

        logger.info(
            "NotificationEngine started with channels: %s",
            list(self._channels.keys()),
        )

    async def stop(self) -> None:
        """Cancel digest loop and flush any buffered notifications."""
        self._running = False
        if self._digest_task and not self._digest_task.done():
            self._digest_task.cancel()
            try:
                await self._digest_task
            except asyncio.CancelledError:
                pass

        # Flush remaining digest messages on shutdown.
        if self._digest_buffer:
            await self._flush_digest()

        logger.info("NotificationEngine stopped.")

    # ── direct send ───────────────────────────────────────────────

    async def send(
        self,
        message: str,
        channel_names: list[str] | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        """Send *message* directly to the specified channels (or all channels)."""
        if self._digest_interval > 0:
            self._digest_buffer.append((message, severity))
            return

        targets = channel_names if channel_names is not None else list(self._channels.keys())
        await self._dispatch(message, targets, severity)

    # ── event handlers ────────────────────────────────────────────

    async def _handle_agent_completed(self, event: AgentTaskCompleted) -> None:
        if not event.success:
            message = f"❌ Agent {event.agent_id} failed task {event.task_id}"
            severity = NotificationSeverity.CRITICAL
        else:
            message = f"✅ Agent {event.agent_id} completed task {event.task_id}: {event.result_summary}"
            severity = NotificationSeverity.INFO

        rules = self._rules.match("AgentTaskCompleted", {"event": event})
        channel_names = self._collect_channels(rules) or list(self._channels.keys())
        await self.send(message, channel_names, severity)

    async def _handle_workflow_completed(self, event: WorkflowCompleted) -> None:
        status = "succeeded" if event.success else "failed"
        message = f"Workflow {event.workflow_id} run {event.run_id} {status} in {event.duration_ms}ms"
        severity = NotificationSeverity.INFO if event.success else NotificationSeverity.WARNING

        rules = self._rules.match("WorkflowCompleted", {"event": event})
        channel_names = self._collect_channels(rules) or ["log"]
        await self.send(message, channel_names, severity)

    async def _handle_any_event(self, event: Any) -> None:
        """Generic handler — matches any event against remaining rules."""
        event_type = type(event).__name__
        # Skip types already handled by specific handlers.
        if event_type in {"AgentTaskCompleted", "WorkflowCompleted"}:
            return

        rules = self._rules.match(event_type, {})
        if not rules:
            return

        message = f"Event {event_type} (source={getattr(event, 'source', '?')})"
        channel_names = self._collect_channels(rules)
        if not channel_names:
            return

        severity = max((r.severity for r in rules), key=lambda s: list(NotificationSeverity).index(s))
        await self.send(message, channel_names, severity)

    # ── digest loop ───────────────────────────────────────────────

    async def _digest_loop(self) -> None:
        """Periodically flush buffered notifications as a digest."""
        while self._running:
            try:
                await asyncio.sleep(self._digest_interval)
                await self._flush_digest()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Digest loop error: %s", exc)

    async def _flush_digest(self) -> None:
        if not self._digest_buffer:
            return

        items = self._digest_buffer[:]
        self._digest_buffer.clear()

        lines = [f"[{sev.value.upper()}] {msg}" for msg, sev in items]
        digest_message = (
            f"📨 Notification digest ({len(lines)} items):\n" + "\n".join(f"• {l}" for l in lines)
        )
        worst = max((sev for _, sev in items), key=lambda s: list(NotificationSeverity).index(s))
        await self._dispatch(digest_message, list(self._channels.keys()), worst)

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _collect_channels(rules: list) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for rule in rules:
            for ch in rule.channels:
                if ch not in seen:
                    seen.add(ch)
                    result.append(ch)
        return result

    async def _dispatch(
        self,
        message: str,
        channel_names: list[str],
        severity: NotificationSeverity,
    ) -> None:
        tasks = []
        for name in channel_names:
            channel = self._channels.get(name)
            if channel is None:
                logger.debug("Channel %r not registered — skipping", name)
                continue
            tasks.append(asyncio.create_task(self._safe_send(channel, message, severity)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_send(
        self,
        channel: NotificationChannel,
        message: str,
        severity: NotificationSeverity,
    ) -> None:
        try:
            ok = await channel.send(message, severity)
            if not ok:
                logger.warning("Channel %r returned False for send", channel.name)
        except Exception as exc:
            logger.exception("Channel %r raised during send: %s", channel.name, exc)
