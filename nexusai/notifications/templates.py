"""NexusAI Notifications — message template registry and renderer."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Built-in templates ────────────────────────────────────────────────────────
# Keys are template names; values are Python str.format()-compatible strings.

TEMPLATES: dict[str, str] = {
    "agent_completed": "✅ Agent {agent_name} completed: {summary}",
    "agent_failed": "❌ Agent {agent_name} failed: {error}",
    "build_failed": "🔴 Build failed on {branch}: {message}",
    "deploy_success": "🚀 Deployed {service} to {environment}",
    "system_alert": "⚠️ System alert: {message}",
    "scheduled_task": "📋 Scheduled task {name}: {status}",
}


def render_template(template_name: str, data: dict) -> str:
    """Render a named template by substituting *data* into its placeholders.

    Falls back to a plain-text representation when the template is unknown or
    a required placeholder is missing, so callers are never left with an
    unformatted string.
    """
    template = TEMPLATES.get(template_name)
    if template is None:
        logger.warning("Unknown notification template: %r", template_name)
        return str(data)

    try:
        return template.format_map(data)
    except KeyError as exc:
        logger.warning(
            "Template %r missing placeholder %s — using raw data fallback",
            template_name,
            exc,
        )
        return template
