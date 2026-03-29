"""Unit tests for GitSkill (uses a real temporary git repo)."""

from __future__ import annotations

import subprocess

import pytest

from nexusai.skills.builtin.git import GitSkill
from nexusai.core.types import SkillContext

pytestmark = pytest.mark.unit


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    readme = repo / "README.md"
    readme.write_text("# Test Repo")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    return repo


@pytest.fixture
def skill() -> GitSkill:
    return GitSkill()


@pytest.fixture
def context(git_repo) -> SkillContext:
    return SkillContext(
        user_id="test_user",
        working_directory=str(git_repo),
    )


class TestGitSkillStatus:
    async def test_git_status_clean(self, skill, context, git_repo):
        result = await skill.execute("git_status", {"cwd": str(git_repo)}, context)
        assert result.success is True
        # A clean repo has no output in --short format
        assert result.output.strip() == "" or "(no output)" in result.output

    async def test_git_status_modified(self, skill, context, git_repo):
        (git_repo / "new_file.txt").write_text("content")

        result = await skill.execute("git_status", {"cwd": str(git_repo)}, context)

        assert result.success is True
        assert "new_file.txt" in result.output


class TestGitSkillDiff:
    async def test_git_diff(self, skill, context, git_repo):
        # Modify a tracked file so diff has something to show
        (git_repo / "README.md").write_text("# Modified")

        result = await skill.execute("git_diff", {"cwd": str(git_repo)}, context)

        assert result.success is True
        assert "README" in result.output or "Modified" in result.output


class TestGitSkillLog:
    async def test_git_log(self, skill, context, git_repo):
        result = await skill.execute("git_log", {"cwd": str(git_repo), "count": 5}, context)

        assert result.success is True
        assert "Initial commit" in result.output


class TestGitSkillCommit:
    async def test_git_commit(self, skill, context, git_repo):
        new_file = git_repo / "feature.txt"
        new_file.write_text("feature work")
        subprocess.run(
            ["git", "add", "feature.txt"], cwd=str(git_repo), check=True, capture_output=True
        )

        result = await skill.execute(
            "git_commit",
            {"message": "Add feature file", "cwd": str(git_repo)},
            context,
        )

        assert result.success is True
        # Verify new commit appears in log
        log_result = await skill.execute("git_log", {"cwd": str(git_repo), "count": 3}, context)
        assert "Add feature file" in log_result.output

    async def test_commit_requires_message(self, skill, context, git_repo):
        result = await skill.execute(
            "git_commit", {"message": "", "cwd": str(git_repo)}, context
        )
        assert result.success is False
        assert "message" in result.output.lower()


class TestGitSkillBranch:
    async def test_git_branch_list(self, skill, context, git_repo):
        result = await skill.execute(
            "git_branch", {"action": "list", "cwd": str(git_repo)}, context
        )
        assert result.success is True
        # Should contain the default branch (master or main)
        assert "master" in result.output or "main" in result.output

    async def test_git_branch_create(self, skill, context, git_repo):
        result = await skill.execute(
            "git_branch",
            {"action": "create", "name": "feature/test", "cwd": str(git_repo)},
            context,
        )
        assert result.success is True

    async def test_git_branch_switch(self, skill, context, git_repo):
        # Create branch first
        subprocess.run(
            ["git", "checkout", "-b", "switch-target"],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
        )
        # Go back to original branch
        subprocess.run(
            ["git", "checkout", "-"],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
        )

        result = await skill.execute(
            "git_branch",
            {"action": "switch", "name": "switch-target", "cwd": str(git_repo)},
            context,
        )
        assert result.success is True


class TestGitSkillTriggers:
    async def test_trigger_git_status(self, skill, context):
        result = await skill.handle_trigger("/git", "status", context)
        assert result.success is True

    async def test_trigger_git_log(self, skill, context):
        result = await skill.handle_trigger("/git", "log 5", context)
        assert result.success is True
        assert "Initial commit" in result.output
