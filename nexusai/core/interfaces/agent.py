"""Agent protocol — interface every agent must implement."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Protocol, runtime_checkable

from nexusai.core.types import (
    AgentConfig,
    AgentContext,
    AgentResult,
    AgentStreamEvent,
    TaskRequest,
)


@runtime_checkable
class Agent(Protocol):
    """Interface every agent must implement.

    Implementations: CoordinatorAgent, CodeAgent, ResearchAgent, etc.
    """

    @property
    def agent_id(self) -> str:
        """Unique identifier for this agent instance."""
        ...

    @property
    def name(self) -> str:
        """Human-readable agent name."""
        ...

    @property
    def description(self) -> str:
        """What this agent does."""
        ...

    @property
    def status(self) -> str:
        """Current AgentStatus value."""
        ...

    @property
    def allowed_skills(self) -> list[str]:
        """Skill names this agent is permitted to use."""
        ...

    async def initialize(self, config: AgentConfig, context: AgentContext) -> None:
        """Set up the agent with configuration and shared context."""
        ...

    async def execute(self, task: TaskRequest) -> AgentResult:
        """Execute a task and return the result."""
        ...

    async def execute_stream(
        self, task: TaskRequest
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        """Execute a task with streaming progress updates."""
        ...

    async def pause(self) -> None:
        """Pause the agent's current execution."""
        ...

    async def resume(self) -> None:
        """Resume a paused agent."""
        ...

    async def cancel(self) -> None:
        """Cancel the agent's current execution."""
        ...

    async def handle_message(self, from_agent: str, message: dict[str, Any]) -> None:
        """Receive a message from another agent."""
        ...

    async def shutdown(self) -> None:
        """Clean up resources."""
        ...
