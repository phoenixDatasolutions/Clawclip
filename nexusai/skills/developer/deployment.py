"""Deployment Skill — deploy and manage Docker containers via the docker CLI."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nexusai.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)


class DeploymentSkill:
    """Deploy and manage Docker containers using subprocess docker CLI calls."""

    @property
    def name(self) -> str:
        return "deployment"

    @property
    def description(self) -> str:
        return "Deploy Docker containers, check status, list containers, and roll back"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="deploy_docker",
                description="Pull and run a Docker image",
                parameters={
                    "type": "object",
                    "properties": {
                        "image": {"type": "string", "description": "Docker image name (e.g. nginx:latest)"},
                        "container_name": {"type": "string", "description": "Container name"},
                        "ports": {"type": "string", "description": "Port mapping (e.g. '8080:80')"},
                        "env": {"type": "object", "description": "Environment variables as key-value pairs"},
                        "detach": {"type": "boolean", "description": "Run in detached mode", "default": True},
                    },
                    "required": ["image"],
                },
                required_permissions=["system.docker"],
            ),
            ToolDefinition(
                name="check_container_status",
                description="Check the status of a Docker container",
                parameters={
                    "type": "object",
                    "properties": {
                        "container_name": {"type": "string", "description": "Container name or ID"},
                    },
                    "required": ["container_name"],
                },
                required_permissions=["system.docker"],
            ),
            ToolDefinition(
                name="rollback_deployment",
                description="Stop the current container and start a previous image version",
                parameters={
                    "type": "object",
                    "properties": {
                        "container_name": {"type": "string", "description": "Container name to stop"},
                        "rollback_image": {"type": "string", "description": "Previous image to deploy"},
                    },
                    "required": ["container_name", "rollback_image"],
                },
                required_permissions=["system.docker"],
            ),
            ToolDefinition(
                name="list_containers",
                description="List running (or all) Docker containers",
                parameters={
                    "type": "object",
                    "properties": {
                        "all": {"type": "boolean", "description": "Include stopped containers", "default": False},
                    },
                },
                required_permissions=["system.docker"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/deploy"]

    @property
    def required_permissions(self) -> list[str]:
        return ["system.docker"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        if tool_name == "deploy_docker":
            return await self._deploy_docker(arguments)
        if tool_name == "check_container_status":
            name = arguments.get("container_name", "")
            if not name:
                return SkillResult(success=False, output="container_name is required")
            return await self._run_docker(["inspect", "--format", "{{.Name}} {{.State.Status}}", name])
        if tool_name == "rollback_deployment":
            return await self._rollback(arguments)
        if tool_name == "list_containers":
            cmd = ["ps"]
            if arguments.get("all"):
                cmd.append("-a")
            return await self._run_docker(cmd)

        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        parts = args.strip().split(maxsplit=1)
        if not parts:
            return await self.execute("list_containers", {}, context)

        subcmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if subcmd == "list":
            return await self.execute("list_containers", {"all": "all" in rest}, context)
        if subcmd == "status":
            return await self.execute("check_container_status", {"container_name": rest}, context)
        if subcmd == "run":
            return await self.execute("deploy_docker", {"image": rest}, context)

        return SkillResult(success=False, output="Usage: /deploy [list|status <name>|run <image>]")

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _run_docker(self, args: list[str], timeout: int = 60) -> SkillResult:
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            if process.returncode != 0:
                return SkillResult(success=False, output=err.strip() or out.strip(), error=err.strip())
            return SkillResult(success=True, output=out.strip() or "(no output)")
        except asyncio.TimeoutError:
            return SkillResult(success=False, output="docker command timed out", error="timeout")
        except FileNotFoundError:
            return SkillResult(success=False, output="docker CLI not found — install Docker", error="docker not found")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _deploy_docker(self, args: dict[str, Any]) -> SkillResult:
        image = args.get("image", "")
        if not image:
            return SkillResult(success=False, output="image is required")

        pull_result = await self._run_docker(["pull", image])
        if not pull_result.success:
            return pull_result

        run_cmd = ["run"]
        if args.get("detach", True):
            run_cmd.append("-d")
        if args.get("container_name"):
            run_cmd += ["--name", args["container_name"]]
        if args.get("ports"):
            run_cmd += ["-p", args["ports"]]
        for key, value in (args.get("env") or {}).items():
            run_cmd += ["-e", f"{key}={value}"]
        run_cmd.append(image)

        return await self._run_docker(run_cmd)

    async def _rollback(self, args: dict[str, Any]) -> SkillResult:
        container_name = args.get("container_name", "")
        rollback_image = args.get("rollback_image", "")
        if not container_name or not rollback_image:
            return SkillResult(success=False, output="container_name and rollback_image are required")

        stop_result = await self._run_docker(["stop", container_name])
        if not stop_result.success:
            logger.warning("Could not stop container %s: %s", container_name, stop_result.output)

        rm_result = await self._run_docker(["rm", container_name])
        if not rm_result.success:
            logger.warning("Could not remove container %s: %s", container_name, rm_result.output)

        return await self._deploy_docker({"image": rollback_image, "container_name": container_name})


def create_skill(config: dict) -> DeploymentSkill:
    return DeploymentSkill()
