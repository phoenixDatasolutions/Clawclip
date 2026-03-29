"""Service Control Skill — list, start, stop, and restart system services."""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"


class ServiceControlSkill:
    """Control Windows services via sc.exe; gracefully degraded on non-Windows."""

    @property
    def name(self) -> str:
        return "services"

    @property
    def description(self) -> str:
        return "List, start, stop, restart, and query Windows system services"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="list_services",
                description="List all Windows services and their states",
                parameters={
                    "type": "object",
                    "properties": {
                        "filter_state": {"type": "string", "description": "Filter by state: running, stopped, all", "default": "all"},
                    },
                },
                required_permissions=["system.services"],
            ),
            ToolDefinition(
                name="start_service",
                description="Start a Windows service by name",
                parameters={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string", "description": "Service name"},
                    },
                    "required": ["service_name"],
                },
                required_permissions=["system.services"],
            ),
            ToolDefinition(
                name="stop_service",
                description="Stop a Windows service by name",
                parameters={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string", "description": "Service name"},
                    },
                    "required": ["service_name"],
                },
                required_permissions=["system.services"],
            ),
            ToolDefinition(
                name="restart_service",
                description="Restart a Windows service by name",
                parameters={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string", "description": "Service name"},
                    },
                    "required": ["service_name"],
                },
                required_permissions=["system.services"],
            ),
            ToolDefinition(
                name="get_service_status",
                description="Get the current status of a Windows service",
                parameters={
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string", "description": "Service name"},
                    },
                    "required": ["service_name"],
                },
                required_permissions=["system.services"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/service", "/svc"]

    @property
    def required_permissions(self) -> list[str]:
        return ["system.services"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        if not _IS_WINDOWS:
            return SkillResult(
                success=False,
                output="Service control is only supported on Windows",
                error="unsupported platform",
            )

        if tool_name == "list_services":
            return await self._list_services(arguments)
        if tool_name == "start_service":
            return await self._sc_command("start", arguments.get("service_name", ""))
        if tool_name == "stop_service":
            return await self._sc_command("stop", arguments.get("service_name", ""))
        if tool_name == "restart_service":
            return await self._restart_service(arguments.get("service_name", ""))
        if tool_name == "get_service_status":
            return await self._get_service_status(arguments.get("service_name", ""))

        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        parts = args.strip().split(maxsplit=1)
        if not parts:
            return await self.execute("list_services", {}, context)

        subcmd = parts[0].lower()
        svc_name = parts[1] if len(parts) > 1 else ""

        subcmd_map = {
            "list": ("list_services", {}),
            "start": ("start_service", {"service_name": svc_name}),
            "stop": ("stop_service", {"service_name": svc_name}),
            "restart": ("restart_service", {"service_name": svc_name}),
            "status": ("get_service_status", {"service_name": svc_name}),
        }

        if subcmd in subcmd_map:
            tool_name, tool_args = subcmd_map[subcmd]
            return await self.execute(tool_name, tool_args, context)

        return SkillResult(success=False, output=f"Unknown subcommand: {subcmd}. Use list/start/stop/restart/status")

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _run_sc(self, args: list[str], timeout: int = 30) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            "sc", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return (
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def _list_services(self, args: dict[str, Any]) -> SkillResult:
        filter_state = args.get("filter_state", "all").lower()
        sc_type = "query"

        try:
            if filter_state == "running":
                code, stdout, stderr = await self._run_sc(["query", "type=", "all", "state=", "active"])
            elif filter_state == "stopped":
                code, stdout, stderr = await self._run_sc(["query", "type=", "all", "state=", "inactive"])
            else:
                code, stdout, stderr = await self._run_sc(["query", "type=", "all", "state=", "all"])

            if code != 0 and stderr:
                return SkillResult(success=False, output=stderr.strip(), error=stderr.strip())

            return SkillResult(success=True, output=stdout.strip() or "(no services found)")
        except asyncio.TimeoutError:
            return SkillResult(success=False, output="sc query timed out", error="timeout")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _sc_command(self, action: str, service_name: str) -> SkillResult:
        if not service_name:
            return SkillResult(success=False, output="service_name is required")
        try:
            code, stdout, stderr = await self._run_sc([action, service_name])
            output = stdout.strip() or stderr.strip() or f"sc {action} completed"
            return SkillResult(success=code == 0, output=output, error=stderr.strip() if code != 0 else None)
        except asyncio.TimeoutError:
            return SkillResult(success=False, output=f"sc {action} timed out", error="timeout")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _restart_service(self, service_name: str) -> SkillResult:
        if not service_name:
            return SkillResult(success=False, output="service_name is required")
        stop_result = await self._sc_command("stop", service_name)
        if not stop_result.success:
            logger.warning("Could not stop %s before restart: %s", service_name, stop_result.output)
        await asyncio.sleep(1)
        return await self._sc_command("start", service_name)

    async def _get_service_status(self, service_name: str) -> SkillResult:
        if not service_name:
            return SkillResult(success=False, output="service_name is required")
        try:
            code, stdout, stderr = await self._run_sc(["query", service_name])
            output = stdout.strip() or stderr.strip() or "(no output)"
            return SkillResult(success=code == 0, output=output, error=stderr.strip() if code != 0 else None)
        except asyncio.TimeoutError:
            return SkillResult(success=False, output="sc query timed out", error="timeout")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))


def create_skill(config: dict) -> ServiceControlSkill:
    return ServiceControlSkill()
