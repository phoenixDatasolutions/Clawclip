"""Unit tests for SkillLoader."""

from __future__ import annotations

import textwrap

import pytest

from nexusai.skills.loader import SkillLoader

pytestmark = pytest.mark.unit


@pytest.fixture
def loader() -> SkillLoader:
    return SkillLoader()


class TestSkillLoaderBuiltin:
    def test_discover_builtin_skills(self, loader):
        skills = loader.discover_builtin_skills()
        assert len(skills) >= 5

    def test_all_builtin_skills_have_name(self, loader):
        for skill in loader.discover_builtin_skills():
            assert skill.name, f"Skill {skill!r} has no name"
            assert isinstance(skill.name, str)
            assert len(skill.name) > 0

    def test_all_builtin_skills_have_tools(self, loader):
        for skill in loader.discover_builtin_skills():
            assert skill.tools, f"Skill '{skill.name}' has no tools"
            assert len(skill.tools) >= 1


class TestSkillLoaderDeveloper:
    def test_discover_developer_skills(self, loader):
        skills = loader.discover_developer_skills()
        assert len(skills) >= 5

    def test_all_developer_skills_have_name(self, loader):
        for skill in loader.discover_developer_skills():
            assert skill.name, f"Developer skill {skill!r} has no name"

    def test_all_developer_skills_have_tools(self, loader):
        for skill in loader.discover_developer_skills():
            assert skill.tools, f"Developer skill '{skill.name}' has no tools"


class TestSkillLoaderDirectory:
    def test_load_from_directory(self, tmp_path):
        """Create a minimal skill module in a temp dir and verify it loads."""
        skill_src = textwrap.dedent(
            """\
            from __future__ import annotations
            from nexusai.core.types import SkillContext, SkillResult, ToolDefinition

            class TestSkill:
                @property
                def name(self) -> str:
                    return "test_dynamic_skill"

                @property
                def description(self) -> str:
                    return "A dynamically loaded test skill"

                @property
                def version(self) -> str:
                    return "0.1.0"

                @property
                def tools(self) -> list[ToolDefinition]:
                    return [
                        ToolDefinition(
                            name="test_tool",
                            description="A test tool",
                            parameters={"type": "object", "properties": {}},
                            required_permissions=[],
                        )
                    ]

                @property
                def triggers(self) -> list[str]:
                    return []

                @property
                def required_permissions(self) -> list[str]:
                    return []

                async def initialize(self, context: SkillContext) -> None:
                    pass

                async def execute(self, tool_name, arguments, context):
                    return SkillResult(success=True, output="ok")

                async def handle_trigger(self, trigger, args, context):
                    return SkillResult(success=True, output="ok")

                async def shutdown(self) -> None:
                    pass

            def create_skill(config: dict) -> TestSkill:
                return TestSkill()
            """
        )
        (tmp_path / "test_skill.py").write_text(skill_src, encoding="utf-8")

        loader = SkillLoader()
        skills = loader.load_from_directory(str(tmp_path))

        assert len(skills) == 1
        assert skills[0].name == "test_dynamic_skill"

    def test_load_from_nonexistent_directory(self):
        loader = SkillLoader()
        skills = loader.load_from_directory("/nonexistent/path/xyz_12345")
        assert skills == []

    def test_load_from_directory_skips_underscore_files(self, tmp_path):
        """Files starting with _ (e.g. __init__.py) must be ignored."""
        (tmp_path / "__init__.py").write_text("# init")
        (tmp_path / "_private.py").write_text("def create_skill(c): return None")

        loader = SkillLoader()
        skills = loader.load_from_directory(str(tmp_path))
        assert skills == []

    def test_load_from_directory_skips_modules_without_factory(self, tmp_path):
        """Modules without create_skill() must be silently skipped."""
        (tmp_path / "no_factory.py").write_text("# just a python file, no factory")

        loader = SkillLoader()
        skills = loader.load_from_directory(str(tmp_path))
        assert skills == []
