"""Unit tests for FileSkill."""

from __future__ import annotations

import pytest

from nexusai.skills.builtin.files import FileSkill
from nexusai.core.types import SkillContext

pytestmark = pytest.mark.unit


@pytest.fixture
def skill() -> FileSkill:
    return FileSkill()


@pytest.fixture
def context() -> SkillContext:
    # No allowed_roots → unrestricted access (test-safe because tmp_path is used)
    return SkillContext(user_id="test_user", config={})


class TestFileSkillReadWrite:
    async def test_read_file(self, skill, context, tmp_path):
        target = tmp_path / "hello.txt"
        target.write_text("hello world", encoding="utf-8")

        result = await skill.execute("read_file", {"path": str(target)}, context)

        assert result.success is True
        assert "hello world" in result.output

    async def test_read_nonexistent(self, skill, context, tmp_path):
        result = await skill.execute(
            "read_file", {"path": str(tmp_path / "nonexistent.txt")}, context
        )
        assert result.success is False

    async def test_write_file(self, skill, context, tmp_path):
        target = tmp_path / "test.txt"

        result = await skill.execute(
            "write_file", {"path": str(target), "content": "hello"}, context
        )

        assert result.success is True
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "hello"

    async def test_list_directory(self, skill, context, tmp_path):
        (tmp_path / "alpha.txt").write_text("a")
        (tmp_path / "beta.txt").write_text("b")
        (tmp_path / "gamma.py").write_text("g")

        result = await skill.execute("list_directory", {"path": str(tmp_path)}, context)

        assert result.success is True
        assert "alpha.txt" in result.output
        assert "beta.txt" in result.output
        assert "gamma.py" in result.output

    async def test_delete_file(self, skill, context, tmp_path):
        target = tmp_path / "delete_me.txt"
        target.write_text("bye")

        result = await skill.execute("delete_file", {"path": str(target)}, context)

        assert result.success is True
        assert not target.exists()

    async def test_copy_file(self, skill, context, tmp_path):
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_text("original content")

        result = await skill.execute(
            "copy_file", {"src": str(src), "dst": str(dst)}, context
        )

        assert result.success is True
        assert src.exists()
        assert dst.exists()
        assert dst.read_text() == "original content"

    async def test_move_file(self, skill, context, tmp_path):
        src = tmp_path / "mover.txt"
        dst = tmp_path / "moved.txt"
        src.write_text("move me")

        result = await skill.execute(
            "move_file", {"src": str(src), "dst": str(dst)}, context
        )

        assert result.success is True
        assert not src.exists()
        assert dst.exists()
        assert dst.read_text() == "move me"

    async def test_search_files(self, skill, context, tmp_path):
        (tmp_path / "one.txt").write_text("1")
        (tmp_path / "two.txt").write_text("2")
        (tmp_path / "script.py").write_text("pass")

        result = await skill.execute(
            "search_files",
            {"directory": str(tmp_path), "pattern": "*.txt"},
            context,
        )

        assert result.success is True
        assert "one.txt" in result.output
        assert "two.txt" in result.output
        # .py should not appear in *.txt results
        assert "script.py" not in result.output


class TestFileSkillSecurity:
    async def test_path_traversal_blocked(self, skill, tmp_path):
        # Provide an allowed_root so traversal can actually be blocked
        restricted_context = SkillContext(
            user_id="test_user",
            config={"allowed_roots": [str(tmp_path)]},
        )
        result = await skill.execute(
            "read_file", {"path": "../../etc/passwd"}, restricted_context
        )
        assert result.success is False


class TestFileSkillTriggers:
    async def test_trigger_ls(self, skill, context, tmp_path):
        result = await skill.handle_trigger("/ls", str(tmp_path), context)
        assert result.success is True

    async def test_trigger_cat(self, skill, context, tmp_path):
        target = tmp_path / "cat_test.txt"
        target.write_text("meow")

        result = await skill.handle_trigger("/cat", str(target), context)

        assert result.success is True
        assert "meow" in result.output
