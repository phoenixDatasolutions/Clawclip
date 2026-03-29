"""ClawClip Webhooks — route incoming webhook events to actions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from clawclip.webhooks.templates.generic import parse_generic_webhook
from clawclip.webhooks.templates.github import parse_github_webhook
from clawclip.webhooks.templates.gitlab import parse_gitlab_webhook

logger = logging.getLogger(__name__)

_PARSERS = {
    "github": parse_github_webhook,
    "gitlab": parse_gitlab_webhook,
    "generic": parse_generic_webhook,
}


def _uuid() -> str:
    return str(uuid4())


@dataclass
class WebhookRoute:
    """Maps an incoming webhook path to a parser and an action."""

    id: str = field(default_factory=_uuid)
    path: str = ""
    parser: str = "generic"  # "github" | "gitlab" | "generic"
    action_type: str = "notification"  # "workflow" | "agent_task" | "notification"
    action_config: dict = field(default_factory=dict)


class WebhookRouter:
    """Parses an incoming webhook and dispatches it to the configured action.

    Actions
    -------
    - ``workflow``    — triggers a workflow by id via *workflow_engine*
    - ``agent_task``  — submits a task to *agent_engine*
    - ``notification`` — sends a notification via *notification_engine*
    """

    def __init__(
        self,
        routes: list[WebhookRoute] | None = None,
        workflow_engine: Any = None,
        agent_engine: Any = None,
        notification_engine: Any = None,
    ) -> None:
        self._routes: list[WebhookRoute] = routes or []
        self._workflow_engine = workflow_engine
        self._agent_engine = agent_engine
        self._notification_engine = notification_engine

    # ── public API ────────────────────────────────────────────────

    async def route(self, path: str, headers: dict, payload: dict) -> dict:
        """Parse *payload* and execute the action for the matching route.

        Returns a result dict with at least ``{"status": "ok"|"error", ...}``.
        """
        route = self._find_route(path)
        if route is None:
            logger.warning("No route registered for path: %r", path)
            return {"status": "error", "reason": f"no route for path {path!r}"}

        parse_fn = _PARSERS.get(route.parser, parse_generic_webhook)
        event = parse_fn(headers, payload)
        if event is None:
            return {"status": "ignored", "reason": "parser returned None"}

        logger.info(
            "Webhook received — path=%r parser=%s action=%s event_type=%s",
            path,
            route.parser,
            route.action_type,
            event.get("event_type", "?"),
        )

        try:
            result = await self._execute_action(route, event)
            return {"status": "ok", "event": event, "action_result": result}
        except Exception as exc:
            logger.exception("Webhook action failed for path %r: %s", path, exc)
            return {"status": "error", "reason": str(exc)}

    def add_route(self, route: WebhookRoute) -> None:
        """Register a new route (replaces any existing route with the same id)."""
        self._routes = [r for r in self._routes if r.id != route.id]
        self._routes.append(route)

    def remove_route(self, route_id: str) -> None:
        """Remove a route by id."""
        self._routes = [r for r in self._routes if r.id != route_id]

    def list_routes(self) -> list[WebhookRoute]:
        return list(self._routes)

    # ── internal helpers ──────────────────────────────────────────

    def _find_route(self, path: str) -> WebhookRoute | None:
        for route in self._routes:
            if route.path == path:
                return route
        return None

    async def _execute_action(self, route: WebhookRoute, event: dict) -> Any:
        action = route.action_type
        cfg = route.action_config

        if action == "workflow":
            if self._workflow_engine is None:
                raise RuntimeError("workflow_engine not configured")
            workflow_id = cfg.get("workflow_id", "")
            return await self._workflow_engine.run(workflow_id, trigger_data=event)

        if action == "agent_task":
            if self._agent_engine is None:
                raise RuntimeError("agent_engine not configured")
            from clawclip.core.types import TaskRequest

            description = cfg.get("task_description", "") or str(event)
            task = TaskRequest(description=description, context={"webhook_event": event})
            return await self._agent_engine.run(task)

        if action == "notification":
            if self._notification_engine is None:
                logger.debug("notification_engine not configured — skipping notification action")
                return None
            message = cfg.get("message_template", "{event_type}: {repo}").format_map(event)
            await self._notification_engine.send(message)
            return None

        raise ValueError(f"Unknown action_type: {action!r}")
