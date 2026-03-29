"""ClawClip Notifications — rule definitions and matching engine."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from uuid import uuid4

from clawclip.core.enums import NotificationSeverity

logger = logging.getLogger(__name__)


def _uuid() -> str:
    return str(uuid4())


@dataclass
class NotificationRule:
    """Maps an event type pattern to a set of notification channels.

    *event_pattern* is a regular expression matched against the event's type
    string (e.g. ``"AgentTaskCompleted"``).  If the pattern matches, the rule
    fires and the notification is sent via every channel listed in *channels*.
    """

    id: str = field(default_factory=_uuid)
    name: str = ""
    event_pattern: str = ".*"
    channels: list[str] = field(default_factory=list)
    severity: NotificationSeverity = NotificationSeverity.INFO
    enabled: bool = True


# ── Default rule set ──────────────────────────────────────────────────────────

DEFAULT_RULES: list[NotificationRule] = [
    NotificationRule(
        name="agent_failures",
        event_pattern=r"AgentTask(Completed|Failed).*",
        channels=["log", "telegram", "webhook"],
        severity=NotificationSeverity.CRITICAL,
    ),
    NotificationRule(
        name="scheduled_tasks",
        event_pattern=r"ScheduledJob.*",
        channels=["log"],
        severity=NotificationSeverity.INFO,
    ),
    NotificationRule(
        name="workflow_events",
        event_pattern=r"Workflow(Started|Completed|StepCompleted)",
        channels=["log"],
        severity=NotificationSeverity.INFO,
    ),
    NotificationRule(
        name="system_alerts",
        event_pattern=r"(AuthFailure|RateLimitHit|ApprovalRequired)",
        channels=["log", "telegram"],
        severity=NotificationSeverity.WARNING,
    ),
]


# ── Rules engine ──────────────────────────────────────────────────────────────


class RulesEngine:
    """Matches incoming event types against notification rules."""

    def __init__(self, rules: list[NotificationRule] | None = None) -> None:
        self._rules: list[NotificationRule] = rules if rules is not None else list(DEFAULT_RULES)
        # Pre-compile patterns for performance.
        self._compiled: list[tuple[re.Pattern[str], NotificationRule]] = []
        for rule in self._rules:
            try:
                self._compiled.append((re.compile(rule.event_pattern), rule))
            except re.error as exc:
                logger.warning("Invalid event_pattern in rule %r: %s", rule.name, exc)

    def match(self, event_type: str, event_data: dict) -> list[NotificationRule]:
        """Return all enabled rules whose *event_pattern* matches *event_type*."""
        matched: list[NotificationRule] = []
        for pattern, rule in self._compiled:
            if not rule.enabled:
                continue
            if pattern.search(event_type):
                matched.append(rule)
        return matched

    def add_rule(self, rule: NotificationRule) -> None:
        """Append a new rule and compile its pattern."""
        try:
            compiled = re.compile(rule.event_pattern)
            self._rules.append(rule)
            self._compiled.append((compiled, rule))
        except re.error as exc:
            logger.error("Could not add rule %r — invalid pattern: %s", rule.name, exc)

    def remove_rule(self, rule_id: str) -> None:
        """Remove a rule by id."""
        self._compiled = [(p, r) for p, r in self._compiled if r.id != rule_id]
        self._rules = [r for r in self._rules if r.id != rule_id]
