"""Skill protocol — interface every skill/plugin must implement."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nexusai.core.types import SkillContext, SkillResult, ToolDefinition


@runtime_checkable
class Skill(Protocol):
    """Interface every skill/plugin must implement.

    Skills wrap system operations (shell, files, git, etc.) into a
    standardized interface that agents can discover and use as tools.
    """

    @property
    def name(self) -> str:
        """Unique skill identifier (e.g., 'shell', 'git', 'files')."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description."""
        ...

    @property
    def version(self) -> str:
        """Skill version string."""
        ...

    @property
    def tools(self) -> list[ToolDefinition]:
        """Tool definitions this skill exposes to LLMs."""
        ...

    @property
    def triggers(self) -> list[str]:
        """Command triggers (e.g., '/sh', '/git', '/ls')."""
        ...

    @property
    def required_permissions(self) -> list[str]:
        """Permissions needed to use this skill (e.g., 'shell.execute')."""
        ...

    async def initialize(self, context: SkillContext) -> None:
        """Called once at startup."""
        ...

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        """Execute a specific tool from this skill."""
        ...

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        """Handle a command trigger (e.g., '/sh ls -la')."""
        ...

    async def shutdown(self) -> None:
        """Clean up resources."""
        ...
