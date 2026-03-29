"""Git Skill — version control operations."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)


class GitSkill:
    """Git version control operations — status, diff, commit, push, log, PR."""

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return "Git version control operations"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="git_status",
                description="Show the working tree status (modified, staged, untracked files)",
                parameters={
                    "type": "object",
                    "properties": {
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                },
                required_permissions=["git.read"],
            ),
            ToolDefinition(
                name="git_diff",
                description="Show changes between commits, working tree, etc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "args": {"type": "string", "description": "Additional git diff arguments (e.g., '--staged', 'HEAD~1')"},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                },
                required_permissions=["git.read"],
            ),
            ToolDefinition(
                name="git_log",
                description="Show commit log",
                parameters={
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "Number of commits to show", "default": 10},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                },
                required_permissions=["git.read"],
            ),
            ToolDefinition(
                name="git_commit",
                description="Create a new commit with staged changes",
                parameters={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Commit message"},
                        "add_all": {"type": "boolean", "description": "Stage all changes before committing", "default": False},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                    "required": ["message"],
                },
                required_permissions=["git.write"],
            ),
            ToolDefinition(
                name="git_push",
                description="Push commits to remote repository",
                parameters={
                    "type": "object",
                    "properties": {
                        "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                        "branch": {"type": "string", "description": "Branch name (optional)"},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                },
                required_permissions=["git.write"],
            ),
            ToolDefinition(
                name="git_branch",
                description="List, create, or switch branches",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "create", "switch"], "description": "Branch action"},
                        "name": {"type": "string", "description": "Branch name (for create/switch)"},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                    "required": ["action"],
                },
                required_permissions=["git.write"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/git"]

    @property
    def required_permissions(self) -> list[str]:
        return ["git.read"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        cwd = arguments.get("cwd", context.working_directory or ".")

        commands: dict[str, list[str]] = {
            "git_status": ["git", "status", "--short"],
            "git_diff": ["git", "diff"] + (arguments.get("args", "").split() if arguments.get("args") else []),
            "git_log": ["git", "log", f"--oneline", f"-{arguments.get('count', 10)}"],
        }

        if tool_name in commands:
            return await self._run_git(commands[tool_name], cwd)

        if tool_name == "git_commit":
            message = arguments.get("message", "")
            if not message:
                return SkillResult(success=False, output="Commit message required")

            if arguments.get("add_all"):
                add_result = await self._run_git(["git", "add", "-A"], cwd)
                if not add_result.success:
                    return add_result

            return await self._run_git(["git", "commit", "-m", message], cwd)

        if tool_name == "git_push":
            cmd = ["git", "push", arguments.get("remote", "origin")]
            if arguments.get("branch"):
                cmd.append(arguments["branch"])
            return await self._run_git(cmd, cwd)

        if tool_name == "git_branch":
            action = arguments.get("action", "list")
            if action == "list":
                return await self._run_git(["git", "branch", "-a"], cwd)
            elif action == "create":
                name = arguments.get("name")
                if not name:
                    return SkillResult(success=False, output="Branch name required")
                return await self._run_git(["git", "checkout", "-b", name], cwd)
            elif action == "switch":
                name = arguments.get("name")
                if not name:
                    return SkillResult(success=False, output="Branch name required")
                return await self._run_git(["git", "checkout", name], cwd)

        return SkillResult(success=False, output=f"Unknown git tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        """Handle /git <subcommand> triggers."""
        if not args:
            return await self.execute("git_status", {}, context)

        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0]
        subargs = parts[1] if len(parts) > 1 else ""

        tool_map = {
            "status": ("git_status", {}),
            "diff": ("git_diff", {"args": subargs}),
            "log": ("git_log", {"count": int(subargs) if subargs.isdigit() else 10}),
            "commit": ("git_commit", {"message": subargs}),
            "push": ("git_push", {}),
            "branch": ("git_branch", {"action": "list"}),
        }

        if subcmd in tool_map:
            tool_name, tool_args = tool_map[subcmd]
            return await self.execute(tool_name, tool_args, context)

        # Fallback: run raw git command
        return await self._run_git(["git"] + args.split(), context.working_directory or ".")

    async def shutdown(self) -> None:
        pass

    @staticmethod
    async def _run_git(cmd: list[str], cwd: str) -> SkillResult:
        """Run a git command and return the result."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

            output = stdout.decode("utf-8", errors="replace")
            error = stderr.decode("utf-8", errors="replace")

            if process.returncode != 0:
                return SkillResult(
                    success=False,
                    output=error or output or "Git command failed",
                    error=error,
                )

            return SkillResult(
                success=True,
                output=output or "(no output)",
            )
        except asyncio.TimeoutError:
            return SkillResult(success=False, output="Git command timed out", error="timeout")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))


def create_skill(config: dict | None = None) -> GitSkill:
    """Factory function for SkillLoader auto-discovery."""
    return GitSkill()
