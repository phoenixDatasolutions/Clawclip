"""Shell Skill — execute bash/PowerShell commands."""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any

from nexusai.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)


class ShellSkill:
    """Execute shell commands with output streaming and timeout protection."""

    def __init__(
        self,
        timeout: int = 60,
        max_output_size: int = 50_000,
        blocked_commands: list[str] | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_output_size = max_output_size
        self._blocked = blocked_commands or ["format", "diskpart"]

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return "Execute bash or PowerShell commands"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="execute_bash",
                description="Execute a bash command and return its output",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The bash command to execute",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Working directory (optional)",
                        },
                    },
                    "required": ["command"],
                },
                required_permissions=["shell.execute"],
            ),
            ToolDefinition(
                name="execute_powershell",
                description="Execute a PowerShell command and return its output",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The PowerShell command to execute",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Working directory (optional)",
                        },
                    },
                    "required": ["command"],
                },
                required_permissions=["shell.execute"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/sh", "/ps", "/bash"]

    @property
    def required_permissions(self) -> list[str]:
        return ["shell.execute"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        command = arguments.get("command", "")
        cwd = arguments.get("cwd", context.working_directory)

        if not command:
            return SkillResult(success=False, output="No command provided")

        # Check blocked commands
        for blocked in self._blocked:
            if blocked.lower() in command.lower():
                return SkillResult(
                    success=False,
                    output=f"Command blocked: contains '{blocked}'",
                )

        if tool_name == "execute_powershell":
            shell_cmd = ["powershell", "-NoProfile", "-Command", command]
        else:
            shell_cmd = ["bash", "-c", command] if platform.system() != "Windows" else ["bash", "-c", command]

        try:
            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout,
            )

            output = stdout.decode("utf-8", errors="replace")
            error_output = stderr.decode("utf-8", errors="replace")

            # Truncate if too large
            if len(output) > self._max_output_size:
                output = output[:self._max_output_size] + "\n... (output truncated)"

            combined = output
            if error_output:
                combined += f"\n[stderr]\n{error_output}"

            return SkillResult(
                success=process.returncode == 0,
                output=combined or "(no output)",
                error=error_output if process.returncode != 0 else None,
            )

        except asyncio.TimeoutError:
            return SkillResult(
                success=False,
                output=f"Command timed out after {self._timeout}s",
                error="timeout",
            )
        except Exception as e:
            return SkillResult(
                success=False,
                output=f"Error executing command: {e}",
                error=str(e),
            )

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        tool_name = "execute_powershell" if trigger == "/ps" else "execute_bash"
        return await self.execute(tool_name, {"command": args}, context)

    async def shutdown(self) -> None:
        pass
