"""CI/CD Skill — query and trigger GitHub Actions workflows via gh CLI."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nexusai.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)


class CICDSkill:
    """Query and trigger GitHub Actions workflows using the gh CLI."""

    @property
    def name(self) -> str:
        return "ci_cd"

    @property
    def description(self) -> str:
        return "Query and trigger GitHub Actions CI/CD workflows via gh CLI"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="get_build_status",
                description="Get the status of recent workflow runs",
                parameters={
                    "type": "object",
                    "properties": {
                        "workflow": {"type": "string", "description": "Workflow name or file (optional)"},
                        "branch": {"type": "string", "description": "Branch name (optional)"},
                        "limit": {"type": "integer", "description": "Max runs to show", "default": 5},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                },
                required_permissions=["git.read"],
            ),
            ToolDefinition(
                name="trigger_build",
                description="Manually trigger a GitHub Actions workflow",
                parameters={
                    "type": "object",
                    "properties": {
                        "workflow": {"type": "string", "description": "Workflow name or file"},
                        "branch": {"type": "string", "description": "Branch to run on", "default": "main"},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                    "required": ["workflow"],
                },
                required_permissions=["git.read"],
            ),
            ToolDefinition(
                name="list_workflows",
                description="List all GitHub Actions workflows in the repository",
                parameters={
                    "type": "object",
                    "properties": {
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                },
                required_permissions=["git.read"],
            ),
            ToolDefinition(
                name="get_workflow_run",
                description="Get details and logs for a specific workflow run",
                parameters={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string", "description": "Workflow run ID"},
                        "cwd": {"type": "string", "description": "Repository directory"},
                    },
                    "required": ["run_id"],
                },
                required_permissions=["git.read"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/ci", "/build"]

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

        if tool_name == "get_build_status":
            return await self._get_build_status(arguments, cwd)
        if tool_name == "trigger_build":
            return await self._trigger_build(arguments, cwd)
        if tool_name == "list_workflows":
            return await self._run_gh(["workflow", "list"], cwd)
        if tool_name == "get_workflow_run":
            run_id = arguments.get("run_id", "")
            if not run_id:
                return SkillResult(success=False, output="run_id is required")
            return await self._run_gh(["run", "view", str(run_id), "--log"], cwd, timeout=60)

        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        parts = args.strip().split(maxsplit=1)
        if not parts:
            return await self.execute("get_build_status", {}, context)

        subcmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if subcmd == "list":
            return await self.execute("list_workflows", {}, context)
        if subcmd == "trigger":
            return await self.execute("trigger_build", {"workflow": rest}, context)
        if subcmd == "run":
            return await self.execute("get_workflow_run", {"run_id": rest}, context)

        return await self.execute("get_build_status", {}, context)

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

    async def _get_build_status(self, args: dict[str, Any], cwd: str) -> SkillResult:
        limit = int(args.get("limit", 5))
        cmd = ["run", "list", "--limit", str(limit)]
        if args.get("workflow"):
            cmd += ["--workflow", args["workflow"]]
        if args.get("branch"):
            cmd += ["--branch", args["branch"]]
        return await self._run_gh(cmd, cwd)

    async def _trigger_build(self, args: dict[str, Any], cwd: str) -> SkillResult:
        workflow = args.get("workflow", "")
        if not workflow:
            return SkillResult(success=False, output="workflow is required")
        branch = args.get("branch", "main")
        return await self._run_gh(["workflow", "run", workflow, "--ref", branch], cwd)


def create_skill(config: dict) -> CICDSkill:
    return CICDSkill()
