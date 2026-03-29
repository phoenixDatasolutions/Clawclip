"""Unit tests for SkillManager."""

from __future__ import annotations

import pytest

from nexusai.skills.manager import SkillManager
from nexusai.skills.builtin.shell import ShellSkill
from nexusai.skills.builtin.files import FileSkill
from nexusai.skills.builtin.git import GitSkill
from nexusai.core.registry import Registry
from nexusai.core.types import SkillContext

pytestmark = pytest.mark.unit


@pytest.fixture
def context(tmp_path) -> SkillContext:
    return SkillContext(
        user_id="test_user",
        working_directory=str(tmp_path),
    )


def _make_manager(*skills) -> SkillManager:
    registry: Registry = Registry("skills")
    for skill in skills:
        registry.register(skill.name, skill)
    manager = SkillManager(skill_registry=registry)
    manager.build_index()
    return manager


class TestSkillManagerRegistration:
    def test_register_and_get_skill(self):
        skill = ShellSkill()
        registry: Registry = Registry("skills")
        registry.register(skill.name, skill)

        assert registry.get("shell") is skill

    def test_list_skills(self):
        skills = [ShellSkill(), FileSkill(), GitSkill()]
        registry: Registry = Registry("skills")
        for s in skills:
            registry.register(s.name, s)

        assert len(list(registry)) == 3

    def test_get_missing_skill(self):
        registry: Registry = Registry("skills")
        result = registry.get("nonexistent")
        assert result is None

    def test_tool_index_built(self):
        manager = _make_manager(ShellSkill(), FileSkill())
        # Both skills' tools must be in the index
        assert "execute_bash" in manager._tool_to_skill
        assert "read_file" in manager._tool_to_skill
        assert manager._tool_to_skill["execute_bash"] == "shell"
        assert manager._tool_to_skill["read_file"] == "files"


class TestSkillManagerTriggers:
    def test_get_trigger_handler_resolves(self):
        manager = _make_manager(ShellSkill())
        # /sh is registered by ShellSkill
        skill_name = manager._trigger_to_skill.get("/sh")
        assert skill_name == "shell"

    async def test_handle_trigger(self, context):
        manager = _make_manager(ShellSkill())
        result = await manager.handle_trigger("/sh", "echo hi", context)
        assert result is not None
        assert result.success is True

    async def test_handle_trigger_unknown_returns_none(self, context):
        manager = _make_manager(ShellSkill())
        result = await manager.handle_trigger("/unknown_trigger_xyz", "args", context)
        assert result is None


class TestSkillManagerExecution:
    async def test_execute_tool(self, context):
        manager = _make_manager(ShellSkill())
        result = await manager.execute("execute_bash", {"command": "echo hi"}, context)
        assert result.success is True
        assert "hi" in result.output

    async def test_execute_missing_tool(self, context):
        manager = _make_manager(ShellSkill())
        result = await manager.execute("nonexistent_tool", {}, context)
        assert result.success is False
        assert "not found" in result.output.lower()


class TestSkillManagerToolListing:
    def test_get_tools_for_agent(self):
        manager = _make_manager(ShellSkill(), FileSkill())
        tools = manager.get_tools_for_agent("agent-1")
        tool_names = {t.name for t in tools}
        assert "execute_bash" in tool_names
        assert "read_file" in tool_names

    def test_get_all_tools_combined(self):
        manager = _make_manager(ShellSkill(), FileSkill(), GitSkill())
        tools = manager.get_all_tools()
        # ShellSkill(2) + FileSkill(7) + GitSkill(6) = 15
        assert len(tools) >= 15
