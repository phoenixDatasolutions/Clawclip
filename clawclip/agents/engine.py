"""Agent Engine — lifecycle management, scheduling, and parallel execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from clawclip.core.enums import AgentStatus
from clawclip.core.events import AgentSpawned, AgentStatusChanged, EventBus
from clawclip.core.registry import Registry
from clawclip.core.types import (
    AgentConfig,
    AgentContext,
    AgentResult,
    AgentStreamEvent,
    TaskRequest,
)

logger = logging.getLogger(__name__)


class AgentEngine:
    """Manages agent lifecycle, spawning, parallel execution, and cost aggregation.

    The engine is the entry point for all agent operations. It:
    - Spawns agents based on type and config
    - Manages running agent instances
    - Handles parallel execution of independent sub-tasks
    - Aggregates costs across agent trees
    """

    def __init__(
        self,
        event_bus: EventBus,
        provider_registry: Registry,
        skill_manager: Any = None,
        storage: Any = None,
        agent_configs: dict[str, AgentConfig] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._provider_registry = provider_registry
        self._skill_manager = skill_manager
        self._storage = storage
        self._agent_configs = agent_configs or {}
        self._running_agents: dict[str, Any] = {}

    async def execute_task(
        self,
        task: TaskRequest,
        agent_type: str | None = None,
    ) -> AgentResult:
        """Execute a task, optionally specifying the agent type.

        If no agent_type is specified, the coordinator agent is used
        to analyze and route the task.
        """
        agent_type = agent_type or "coordinator"

        config = self._agent_configs.get(agent_type)
        if not config:
            return AgentResult(
                success=False,
                output=f"Agent type '{agent_type}' not configured",
                agent_type=agent_type,
            )

        # Resolve the provider
        provider = self._provider_registry.get(config.provider)
        if not provider:
            return AgentResult(
                success=False,
                output=f"Provider '{config.provider}' not found for agent '{agent_type}'",
                agent_type=agent_type,
            )

        # Create agent context
        context = AgentContext(
            event_bus=self._event_bus,
            skill_manager=self._skill_manager,
            storage=self._storage,
            user_id=task.user_id,
            platform=task.platform,
            channel_id=task.channel_id,
            conversation_id=task.conversation_id,
        )
        # Inject the provider into context
        context._provider = provider  # type: ignore[attr-defined]

        # Spawn the agent
        agent = await self.spawn_agent(agent_type, config, context)

        try:
            result = await agent.execute(task)
            return result
        finally:
            self._running_agents.pop(agent.agent_id, None)
            await agent.shutdown()

    async def execute_task_stream(
        self,
        task: TaskRequest,
        agent_type: str | None = None,
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        """Execute a task with streaming progress updates."""
        agent_type = agent_type or "coordinator"

        config = self._agent_configs.get(agent_type)
        if not config:
            yield AgentStreamEvent(
                agent_id="",
                event_type="error",
                text=f"Agent type '{agent_type}' not configured",
            )
            return

        provider = self._provider_registry.get(config.provider)
        if not provider:
            yield AgentStreamEvent(
                agent_id="",
                event_type="error",
                text=f"Provider '{config.provider}' not found",
            )
            return

        context = AgentContext(
            event_bus=self._event_bus,
            skill_manager=self._skill_manager,
            storage=self._storage,
            user_id=task.user_id,
            platform=task.platform,
            channel_id=task.channel_id,
            conversation_id=task.conversation_id,
        )
        context._provider = provider  # type: ignore[attr-defined]

        agent = await self.spawn_agent(agent_type, config, context)

        try:
            async for event in agent.execute_stream(task):
                yield event
        finally:
            self._running_agents.pop(agent.agent_id, None)
            await agent.shutdown()

    async def spawn_agent(
        self,
        agent_type: str,
        config: AgentConfig,
        context: AgentContext,
    ) -> Any:
        """Create and register a new agent instance."""
        from clawclip.agents.base_agent import BaseAgent

        # Create agent based on type
        agent = self._create_agent(agent_type)
        await agent.initialize(config, context)

        self._running_agents[agent.agent_id] = agent

        await self._event_bus.publish(AgentSpawned(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            agent_type=agent_type,
            parent_agent_id=context.parent_agent_id,
        ))

        logger.info("Spawned agent: %s (%s)", agent_type, agent.agent_id[:8])
        return agent

    def _create_agent(self, agent_type: str) -> Any:
        """Create an agent instance by type."""
        from clawclip.agents.base_agent import BaseAgent
        from clawclip.agents.builtin.code_agent import CodeAgent
        from clawclip.agents.builtin.devops_agent import DevOpsAgent
        from clawclip.agents.builtin.research_agent import ResearchAgent
        from clawclip.agents.builtin.system_agent import SystemAgent
        from clawclip.agents.coordinator import CoordinatorAgent

        agent_classes: dict[str, type] = {
            "coordinator": CoordinatorAgent,
            "code": CodeAgent,
            "research": ResearchAgent,
            "system": SystemAgent,
            "devops": DevOpsAgent,
        }

        agent_class = agent_classes.get(agent_type, BaseAgent)
        return agent_class()

    async def cancel_agent(self, agent_id: str) -> bool:
        """Cancel a running agent."""
        agent = self._running_agents.get(agent_id)
        if agent:
            await agent.cancel()
            return True
        return False

    async def pause_agent(self, agent_id: str) -> bool:
        """Pause a running agent."""
        agent = self._running_agents.get(agent_id)
        if agent:
            await agent.pause()
            return True
        return False

    async def resume_agent(self, agent_id: str) -> bool:
        """Resume a paused agent."""
        agent = self._running_agents.get(agent_id)
        if agent:
            await agent.resume()
            return True
        return False

    def get_running_agents(self) -> list[Any]:
        """Get all currently running agents."""
        return list(self._running_agents.values())

    def get_agent(self, agent_id: str) -> Any | None:
        """Get an agent by ID."""
        return self._running_agents.get(agent_id)

    async def execute_parallel(
        self,
        tasks: list[tuple[str, TaskRequest]],
    ) -> list[AgentResult]:
        """Execute multiple tasks in parallel, each with its own agent.

        Args:
            tasks: List of (agent_type, task) tuples.

        Returns:
            List of results in the same order as tasks.
        """
        async def _run(agent_type: str, task: TaskRequest) -> AgentResult:
            return await self.execute_task(task, agent_type=agent_type)

        results = await asyncio.gather(
            *[_run(at, t) for at, t in tasks],
            return_exceptions=True,
        )

        return [
            r if isinstance(r, AgentResult)
            else AgentResult(success=False, output=str(r))
            for r in results
        ]
