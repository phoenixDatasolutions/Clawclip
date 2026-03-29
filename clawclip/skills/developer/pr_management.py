"""PR Management Skill — create, list, diff, merge, and close GitHub pull requests via gh CLI."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)


class PRManagementSkill:
    """Manage GitHub pull requests using the gh CLI."""

    @property
    def name(self) -> str:
        return "pr_management"

    @property
    def description(self) -> str:
        return "Create, list, diff, merge, and close GitHub pull requests via gh CLI"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="create_pr",
                description="Create a GitHub pull request",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "PR title"},
                        "body": {"type": "string", "description": "PR description body"},
                        "base": {"type": "string", "description": "Base branch", "default": "main"},
                        "draft": {"type": "boolean", "description": "Create as draft PR", "default": False},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                    "required": ["title"],
                },
                required_permissions=["git.write"],
            ),
            ToolDefinition(
                name="list_prs",
                description="List open pull requests",
                parameters={
                    "type": "object",
                    "properties": {
                        "state": {"type": "string", "enum": ["open", "closed", "merged", "all"], "default": "open"},
                        "limit": {"type": "integer", "description": "Max PRs to return", "default": 10},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                },
                required_permissions=["git.read"],
            ),
            ToolDefinition(
                name="get_pr_diff",
                description="Get the diff of a pull request",
                parameters={
                    "type": "object",
                    "properties": {
                        "pr_number": {"type": "integer", "description": "PR number"},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                    "required": ["pr_number"],
                },
                required_permissions=["git.read"],
            ),
            ToolDefinition(
                name="merge_pr",
                description="Merge a pull request",
                parameters={
                    "type": "object",
                    "properties": {
                        "pr_number": {"type": "integer", "description": "PR number"},
                        "method": {"type": "string", "enum": ["merge", "squash", "rebase"], "default": "merge"},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                    "required": ["pr_number"],
                },
                required_permissions=["git.write"],
            ),
            ToolDefinition(
                name="close_pr",
                description="Close a pull request without merging",
                parameters={
                    "type": "object",
                    "properties": {
                        "pr_number": {"type": "integer", "description": "PR number"},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                    "required": ["pr_number"],
                },
                required_permissions=["git.write"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/pr"]

    @property
    def required_permissions(self) -> list[str]:
        return ["git.write"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        cwd = arguments.get("cwd", context.working_directory or ".")

        if tool_name == "create_pr":
            return await self._create_pr(arguments, cwd)
        if tool_name == "list_prs":
            return await self._list_prs(arguments, cwd)
        if tool_name == "get_pr_diff":
            return await self._get_pr_diff(arguments, cwd)
        if tool_name == "merge_pr":
            return await self._merge_pr(arguments, cwd)
        if tool_name == "close_pr":
            return await self._close_pr(arguments, cwd)

        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        parts = args.strip().split(maxsplit=1)
        if not parts:
            return await self.execute("list_prs", {}, context)

        subcmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if subcmd == "list":
            return await self.execute("list_prs", {}, context)
        if subcmd == "create":
            return await self.execute("create_pr", {"title": rest}, context)
        if subcmd == "diff" and rest.isdigit():
            return await self.execute("get_pr_diff", {"pr_number": int(rest)}, context)
        if subcmd == "merge" and rest.isdigit():
            return await self.execute("merge_pr", {"pr_number": int(rest)}, context)
        if subcmd == "close" and rest.isdigit():
            return await self.execute("close_pr", {"pr_number": int(rest)}, context)

        return await self.execute("list_prs", {}, context)

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _run_gh(self, args: list[str], cwd: str, timeout: int = 30) -> SkillResult:
        try:
            process = await asyncio.create_subprocess_exec(
                "gh", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            if process.returncode != 0:
                return SkillResult(success=False, output=err.strip() or out.strip(), error=err.strip())
            return SkillResult(success=True, output=out.strip() or "(no output)")
        except asyncio.TimeoutError:
            return SkillResult(success=False, output="gh command timed out", error="timeout")
        except FileNotFoundError:
            return SkillResult(success=False, output="gh CLI not found — install GitHub CLI", error="gh not found")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _create_pr(self, args: dict[str, Any], cwd: str) -> SkillResult:
        title = args.get("title", "")
        if not title:
            return SkillResult(success=False, output="title is required")

        cmd = ["pr", "create", "--title", title]
        if args.get("body"):
            cmd += ["--body", args["body"]]
        if args.get("base"):
            cmd += ["--base", args["base"]]
        if args.get("draft"):
            cmd.append("--draft")

        return await self._run_gh(cmd, cwd)

    async def _list_prs(self, args: dict[str, Any], cwd: str) -> SkillResult:
        state = args.get("state", "open")
        limit = int(args.get("limit", 10))
        cmd = ["pr", "list", "--state", state, "--limit", str(limit)]
        return await self._run_gh(cmd, cwd)

    async def _get_pr_diff(self, args: dict[str, Any], cwd: str) -> SkillResult:
        pr_number = args.get("pr_number")
        if not pr_number:
            return SkillResult(success=False, output="pr_number is required")
        return await self._run_gh(["pr", "diff", str(pr_number)], cwd, timeout=60)

    async def _merge_pr(self, args: dict[str, Any], cwd: str) -> SkillResult:
        pr_number = args.get("pr_number")
        if not pr_number:
            return SkillResult(success=False, output="pr_number is required")
        method = args.get("method", "merge")
        flag_map = {"merge": "--merge", "squash": "--squash", "rebase": "--rebase"}
        flag = flag_map.get(method, "--merge")
        return await self._run_gh(["pr", "merge", str(pr_number), flag], cwd)

    async def _close_pr(self, args: dict[str, Any], cwd: str) -> SkillResult:
        pr_number = args.get("pr_number")
        if not pr_number:
            return SkillResult(success=False, output="pr_number is required")
        return await self._run_gh(["pr", "close", str(pr_number)], cwd)


def create_skill(config: dict) -> PRManagementSkill:
    return PRManagementSkill()
