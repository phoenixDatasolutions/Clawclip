"""Unit tests for nexusai.agents.sandbox — AgentSandbox permission enforcement."""

from __future__ import annotations

import pytest

from nexusai.agents.sandbox import AgentSandbox
from nexusai.core.types import ToolDefinition


def _tool(name: str, permissions: list[str] | None = None) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="",
        parameters={},
        required_permissions=permissions or [],
    )


@pytest.mark.unit
class TestAgentSandbox:

    def test_wildcard_allows_all(self) -> None:
        """'*' in allowed_skills grants access to any skill."""
        sandbox = AgentSandbox(["*"])
        assert sandbox.can_use_skill("anything") is True
        assert sandbox.can_use_skill("shell") is True
        assert sandbox.can_use_skill("files") is True

    def test_empty_denies_all(self) -> None:
        """Empty allowed_skills list denies every skill."""
        sandbox = AgentSandbox([])
        assert sandbox.can_use_skill("shell") is False

    def test_specific_skill_allowed(self) -> None:
        """Explicitly listed skill is allowed."""
        sandbox = AgentSandbox(["shell"])
        assert sandbox.can_use_skill("shell") is True

    def test_other_skill_denied(self) -> None:
        """Skills not in the allowed list are denied."""
        sandbox = AgentSandbox(["shell"])
        assert sandbox.can_use_skill("files") is False

    def test_filter_tools(self) -> None:
        """filter_tools returns only tools whose skill prefix is allowed."""
        sandbox = AgentSandbox(["shell", "git"])
        tools = [
            _tool("shell__run"),
            _tool("shell__ls"),
            _tool("files__read"),
            _tool("git__commit"),
            _tool("web__search"),
        ]
        allowed = sandbox.filter_tools(tools)
        names = {t.name for t in allowed}
        assert "shell__run" in names
        assert "shell__ls" in names
        assert "git__commit" in names
        assert "files__read" not in names
        assert "web__search" not in names

    def test_tool_specific_permission(self) -> None:
        """allowed_tools=['shell:execute_bash'] permits only that tool."""
        sandbox = AgentSandbox(
            allowed_skills=["shell"],
            allowed_tools=["shell:execute_bash"],
        )
        assert sandbox.can_use_tool("shell", "execute_bash") is True
        assert sandbox.can_use_tool("shell", "list_directory") is False
