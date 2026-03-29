"""Unit tests for ShellSkill."""

from __future__ import annotations

import pytest

from nexusai.skills.builtin.shell import ShellSkill
from nexusai.core.types import SkillContext

pytestmark = pytest.mark.unit


@pytest.fixture
def skill() -> ShellSkill:
    return ShellSkill(timeout=10, max_output_size=1000)


@pytest.fixture
def context(tmp_path) -> SkillContext:
    return SkillContext(
        user_id="test_user",
        agent_id="test_agent",
        working_directory=str(tmp_path),
    )


class TestShellSkillExecution:
    async def test_execute_bash_simple(self, skill, context):
        result = await skill.execute("execute_bash", {"command": "echo hello"}, context)
        assert result.success is True
        assert "hello" in result.output

    async def test_execute_bash_exit_code(self, skill, context):
        result = await skill.execute("execute_bash", {"command": "exit 1"}, context)
        assert result.success is False

    async def test_execute_blocked_command(self, skill, context):
        result = await skill.execute("execute_bash", {"command": "format C: /fs:ntfs"}, context)
        assert result.success is False
        assert "blocked" in result.output.lower()

    async def test_timeout_protection(self, context):
        fast_skill = ShellSkill(timeout=1)
        result = await fast_skill.execute(
            "execute_bash", {"command": "sleep 60"}, context
        )
        assert result.success is False
        assert "timed out" in result.output.lower() or "timeout" in result.output.lower()

    async def test_cwd_respected(self, skill, context, tmp_path):
        result = await skill.execute(
            "execute_bash",
            {"command": "pwd", "cwd": str(tmp_path)},
            context,
        )
        assert result.success is True
        # On Windows, Git Bash maps C:\... to /c/... or /tmp/..., so we compare
        # only the final path component (the unique pytest tmp dir name) which is
        # stable regardless of drive-letter style.
        unique_part = tmp_path.name.lower()
        assert unique_part in result.output.lower()

    async def test_stderr_captured(self, skill, context):
        result = await skill.execute(
            "execute_bash",
            {"command": "echo error_msg >&2"},
            context,
        )
        assert "error_msg" in result.output

    async def test_output_truncated(self, context):
        tiny_skill = ShellSkill(max_output_size=50)
        # Generate more than 50 bytes of output
        result = await tiny_skill.execute(
            "execute_bash",
            {"command": "python -c \"print('x' * 200)\""},
            context,
        )
        assert result.success is True
        assert "truncated" in result.output


class TestShellSkillTriggers:
    async def test_trigger_sh(self, skill, context):
        result = await skill.handle_trigger("/sh", "echo test", context)
        assert result.success is True

    async def test_trigger_bash(self, skill, context):
        result = await skill.handle_trigger("/bash", "echo test", context)
        assert result.success is True


class TestShellSkillMetadata:
    def test_tool_definitions(self, skill):
        tool_names = [t.name for t in skill.tools]
        assert "execute_bash" in tool_names
        assert "execute_powershell" in tool_names

    def test_required_permissions(self, skill):
        assert skill.required_permissions == ["shell.execute"]
