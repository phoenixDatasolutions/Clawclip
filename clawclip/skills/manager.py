"""Skill Manager — execute skills, manage permissions, route triggers."""

from __future__ import annotations

import logging
import time
from typing import Any

from clawclip.core.events import EventBus, SkillExecuted
from clawclip.core.registry import Registry
from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)


class SkillManager:
    """Manages skill execution, permissions, and tool routing.

    Responsibilities:
    - Execute tools by name, routing to the correct skill
    - Handle command triggers (/sh, /ls, /git, etc.)
    - Provide filtered tool definitions for agents based on permissions
    - Emit SkillExecuted events for tracking
    """

    def __init__(
        self,
        skill_registry: Registry,
        event_bus: EventBus | None = None,
    ) -> None:
        self._registry = skill_registry
        self._event_bus = event_bus
        self._tool_to_skill: dict[str, str] = {}
        self._trigger_to_skill: dict[str, str] = {}

    def build_index(self) -> None:
        """Build tool→skill and trigger→skill lookup indexes."""
        self._tool_to_skill.clear()
        self._trigger_to_skill.clear()

        for skill_name, skill in self._registry:
            for tool in skill.tools:
                self._tool_to_skill[tool.name] = skill_name
            for trigger in skill.triggers:
                self._trigger_to_skill[trigger] = skill_name

        logger.info(
            "Skill index built: %d tools, %d triggers",
            len(self._tool_to_skill),
            len(self._trigger_to_skill),
        )

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        """Execute a tool by name, routing to the correct skill."""
        skill_name = self._tool_to_skill.get(tool_name)
        if not skill_name:
            return SkillResult(
                success=False,
                output=f"Tool '{tool_name}' not found",
                error=f"No skill registered for tool '{tool_name}'",
            )

        skill = self._registry.get(skill_name)
        if not skill:
            return SkillResult(
                success=False,
                output=f"Skill '{skill_name}' not found",
                error=f"Skill '{skill_name}' not registered",
            )

        start_time = time.monotonic()
        try:
            result = await skill.execute(tool_name, arguments, context)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            if self._event_bus:
                await self._event_bus.publish(SkillExecuted(
                    skill_name=skill_name,
                    tool_name=tool_name,
                    agent_id=context.agent_id or "",
                    user_id=context.user_id,
                    duration_ms=duration_ms,
                    success=result.success,
                ))

            return result

        except Exception as e:
            logger.exception("Skill %s.%s execution failed", skill_name, tool_name)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            if self._event_bus:
                await self._event_bus.publish(SkillExecuted(
                    skill_name=skill_name,
                    tool_name=tool_name,
                    agent_id=context.agent_id or "",
                    user_id=context.user_id,
                    duration_ms=duration_ms,
                    success=False,
                ))

            return SkillResult(
                success=False,
                output=f"Error: {e}",
                error=str(e),
            )

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult | None:
        """Handle a command trigger (e.g., '/sh ls -la').

        Returns None if no skill handles this trigger.
        """
        skill_name = self._trigger_to_skill.get(trigger)
        if not skill_name:
            return None

        skill = self._registry.get(skill_name)
        if not skill:
            return None

        try:
            return await skill.handle_trigger(trigger, args, context)
        except Exception as e:
            logger.exception("Trigger %s handling failed", trigger)
            return SkillResult(
                success=False,
                output=f"Error handling {trigger}: {e}",
                error=str(e),
            )

    def get_tools_for_agent(self, agent_id: str) -> list[ToolDefinition]:
        """Get all tool definitions available to an agent.

        TODO: Filter by agent's allowed_skills permissions.
        """
        tools: list[ToolDefinition] = []
        for _, skill in self._registry:
            tools.extend(skill.tools)
        return tools

    def get_all_tools(self) -> list[ToolDefinition]:
        """Get all registered tool definitions."""
        tools: list[ToolDefinition] = []
        for _, skill in self._registry:
            tools.extend(skill.tools)
        return tools

    def get_all_triggers(self) -> list[str]:
        """Get all registered command triggers."""
        return list(self._trigger_to_skill.keys())
