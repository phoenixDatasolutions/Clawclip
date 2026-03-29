"""Base Agent — common LLM loop with tool calling via SkillManager."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from nexusai.core.enums import AgentStatus
from nexusai.core.events import (
    AgentStatusChanged,
    AgentTaskCompleted,
    AgentTaskStarted,
    EventBus,
)
from nexusai.core.types import (
    AgentConfig,
    AgentContext,
    AgentResult,
    AgentStreamEvent,
    LLMMessage,
    SkillContext,
    TaskRequest,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger(__name__)


class BaseAgent:
    """Base agent class implementing the core LLM loop.

    The loop:
    1. Send messages + tool definitions to the LLM
    2. If LLM returns tool calls → execute via SkillManager → append results → repeat
    3. If LLM returns text → return as result
    """

    def __init__(self) -> None:
        self._agent_id: str = str(uuid4())
        self._name: str = ""
        self._description: str = ""
        self._status: AgentStatus = AgentStatus.IDLE
        self._config: AgentConfig | None = None
        self._context: AgentContext | None = None
        self._conversation: list[LLMMessage] = []

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def status(self) -> str:
        return self._status.value

    @property
    def allowed_skills(self) -> list[str]:
        return self._config.allowed_skills if self._config else []

    async def initialize(self, config: AgentConfig, context: AgentContext) -> None:
        """Set up the agent with configuration and shared context."""
        self._config = config
        self._context = context
        self._name = config.agent_type
        self._status = AgentStatus.IDLE
        logger.info("Agent %s (%s) initialized", self._name, self._agent_id[:8])

    async def execute(self, task: TaskRequest) -> AgentResult:
        """Execute a task using the LLM loop."""
        if not self._config or not self._context:
            raise RuntimeError("Agent not initialized. Call initialize() first.")

        self._status = AgentStatus.RUNNING
        start_time = time.monotonic()
        total_cost = 0.0

        event_bus: EventBus | None = self._context.event_bus
        if event_bus:
            await event_bus.publish(AgentTaskStarted(
                agent_id=self._agent_id, task_id=task.task_id,
                description=task.description,
            ))
            await event_bus.publish(AgentStatusChanged(
                agent_id=self._agent_id,
                old_status=AgentStatus.IDLE.value,
                new_status=AgentStatus.RUNNING.value,
            ))

        try:
            # Initialize conversation with user task
            self._conversation = [
                LLMMessage(role="user", content=task.description),
            ]

            # Get the LLM provider
            provider = self._get_provider()
            if not provider:
                return AgentResult(
                    success=False, output="No LLM provider available",
                    agent_id=self._agent_id, agent_type=self._config.agent_type,
                )

            # Get available tools
            tools = self._get_tools()

            # Main agent loop
            for turn in range(self._config.max_turns):
                response = await provider.generate(
                    messages=self._conversation,
                    model=self._config.model,
                    tools=tools if tools else None,
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    system_prompt=self._config.system_prompt,
                )

                total_cost += response.cost_usd

                if response.tool_calls:
                    # Execute tool calls
                    self._conversation.append(LLMMessage(
                        role="assistant", content=response.content,
                        tool_calls=response.tool_calls,
                    ))

                    for tool_call in response.tool_calls:
                        result = await self._execute_tool(tool_call)
                        self._conversation.append(LLMMessage(
                            role="tool", content=result.output,
                            tool_call_id=result.tool_call_id,
                        ))
                else:
                    # No tool calls — we have our final answer
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    self._status = AgentStatus.COMPLETED

                    if event_bus:
                        await event_bus.publish(AgentTaskCompleted(
                            agent_id=self._agent_id, task_id=task.task_id,
                            success=True, result_summary=response.content[:200],
                            cost_usd=total_cost, duration_ms=duration_ms,
                        ))

                    return AgentResult(
                        success=True, output=response.content,
                        cost_usd=total_cost, duration_ms=duration_ms,
                        agent_id=self._agent_id, agent_type=self._config.agent_type,
                    )

            # Max turns reached
            self._status = AgentStatus.COMPLETED
            return AgentResult(
                success=True,
                output=self._conversation[-1].content if self._conversation else "Max turns reached",
                cost_usd=total_cost,
                duration_ms=int((time.monotonic() - start_time) * 1000),
                agent_id=self._agent_id, agent_type=self._config.agent_type,
            )

        except Exception as e:
            self._status = AgentStatus.FAILED
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.exception("Agent %s failed: %s", self._name, e)

            if event_bus:
                await event_bus.publish(AgentTaskCompleted(
                    agent_id=self._agent_id, task_id=task.task_id,
                    success=False, result_summary=str(e),
                    cost_usd=total_cost, duration_ms=duration_ms,
                ))

            return AgentResult(
                success=False, output=str(e),
                cost_usd=total_cost, duration_ms=duration_ms,
                agent_id=self._agent_id, agent_type=self._config.agent_type,
            )

    async def execute_stream(
        self, task: TaskRequest
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        """Execute with streaming progress updates."""
        # For now, delegate to non-streaming execute and yield the result
        result = await self.execute(task)
        yield AgentStreamEvent(
            agent_id=self._agent_id,
            event_type="complete",
            text=result.output,
            metadata={"cost_usd": result.cost_usd, "duration_ms": result.duration_ms},
        )

    async def pause(self) -> None:
        self._status = AgentStatus.PAUSED

    async def resume(self) -> None:
        self._status = AgentStatus.RUNNING

    async def cancel(self) -> None:
        self._status = AgentStatus.CANCELLED

    async def handle_message(self, from_agent: str, message: dict[str, Any]) -> None:
        """Receive a message from another agent."""
        logger.info("Agent %s received message from %s", self._name, from_agent)

    async def shutdown(self) -> None:
        """Clean up resources."""
        self._status = AgentStatus.IDLE
        self._conversation.clear()

    def _get_provider(self) -> Any:
        """Get the LLM provider from the DI container."""
        if not self._context:
            return None
        # The provider is resolved via the context
        # In practice, the AgentEngine injects the correct provider
        return getattr(self._context, "_provider", None)

    def _get_tools(self) -> list[Any]:
        """Get available tool definitions from the SkillManager."""
        if not self._context or not self._context.skill_manager:
            return []
        # Get tools filtered by this agent's allowed skills
        try:
            return self._context.skill_manager.get_tools_for_agent(self._agent_id)
        except Exception:
            return []

    async def _execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call via the SkillManager."""
        if not self._context or not self._context.skill_manager:
            return ToolResult(
                tool_call_id=tool_call.id,
                output="No skill manager available",
                is_error=True,
            )

        try:
            skill_context = SkillContext(
                user_id=self._context.user_id,
                agent_id=self._agent_id,
                conversation_id=self._context.conversation_id,
                platform=self._context.platform,
                channel_id=self._context.channel_id,
            )
            result = await self._context.skill_manager.execute(
                tool_call.name, tool_call.arguments, skill_context,
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                output=result.output,
                is_error=not result.success,
            )
        except Exception as e:
            logger.exception("Tool %s execution failed", tool_call.name)
            return ToolResult(
                tool_call_id=tool_call.id,
                output=f"Error: {e}",
                is_error=True,
            )
