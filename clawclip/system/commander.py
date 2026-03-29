"""Shell command execution with timeout and output streaming."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from clawclip.core.config import NexusConfig
from clawclip.utils.logger import get_logger
from clawclip.utils.security import validate_shell_command

log = get_logger(__name__)

# Module-level config — loaded lazily on first use
_config: NexusConfig | None = None


def _get_config() -> NexusConfig:
    """Return the module-level NexusConfig, loading it if needed."""
    global _config
    if _config is None:
        _config = NexusConfig()
        _config.load()
    return _config


def set_config(config: NexusConfig) -> None:
    """Allow callers to inject a pre-loaded config instance."""
    global _config
    _config = config


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    return_code: int
    duration_ms: int
    was_killed: bool = False


class ShellCommander:
    """Execute shell commands via bash or PowerShell."""

    def __init__(self) -> None:
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    async def execute(
        self,
        command: str,
        shell: str = "bash",
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        """Execute a command and return the result."""
        cfg = _get_config()
        timeout = timeout or cfg.get("shell.command_timeout", 60)
        cwd = cwd or cfg.get("shell.default_cwd", "D:\\Projects")

        # Safety check
        warning = validate_shell_command(command)
        if warning:
            return CommandResult(
                stdout="", stderr=warning, return_code=-1, duration_ms=0
            )

        if shell == "powershell":
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            cmd = ["bash", "-c", command]

        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        task_id = str(id(proc))
        self._active_processes[task_id] = proc

        was_killed = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            was_killed = True
            stdout_bytes = b""
            stderr_bytes = f"Command timed out after {timeout}s".encode()
        finally:
            self._active_processes.pop(task_id, None)

        duration_ms = int((time.monotonic() - start) * 1000)

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        # Cap output size
        max_size = cfg.get("shell.max_output_size", 50000)
        if len(stdout) > max_size:
            stdout = stdout[:max_size] + f"\n\n... (truncated at {max_size} chars)"
        if len(stderr) > max_size:
            stderr = stderr[:max_size] + f"\n\n... (truncated at {max_size} chars)"

        return CommandResult(
            stdout=stdout,
            stderr=stderr,
            return_code=proc.returncode or 0,
            duration_ms=duration_ms,
            was_killed=was_killed,
        )

    async def execute_streaming(
        self,
        command: str,
        shell: str = "bash",
        timeout: int | None = None,
        cwd: str | None = None,
    ):
        """Execute a command and yield stdout lines as they arrive."""
        cfg = _get_config()
        timeout = timeout or cfg.get("shell.command_timeout", 60)
        cwd = cwd or cfg.get("shell.default_cwd", "D:\\Projects")

        warning = validate_shell_command(command)
        if warning:
            yield warning
            return

        if shell == "powershell":
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            cmd = ["bash", "-c", command]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )

        task_id = str(id(proc))
        self._active_processes[task_id] = proc

        try:
            async for line in proc.stdout:
                yield line.decode("utf-8", errors="replace")

            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            yield f"\n\nCommand timed out after {timeout}s"
        finally:
            self._active_processes.pop(task_id, None)

    def cancel_all(self) -> int:
        count = 0
        for proc in self._active_processes.values():
            if proc.returncode is None:
                proc.kill()
                count += 1
        return count


# Singleton
commander = ShellCommander()
