"""Windows service management via sc.exe and net.exe."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass


@dataclass
class ServiceInfo:
    name: str
    display_name: str
    state: str


async def _run_cmd(cmd: list[str]) -> tuple[str, int]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode("utf-8", errors="replace"), proc.returncode or 0


async def list_services(filter_running: bool = False) -> list[ServiceInfo]:
    """List Windows services."""
    state_filter = "state= running" if filter_running else "state= all"
    output, _ = await _run_cmd(["sc", "query", "type=", "service", state_filter])

    services = []
    current_name = ""
    current_display = ""
    current_state = ""

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("SERVICE_NAME:"):
            current_name = line.split(":", 1)[1].strip()
        elif line.startswith("DISPLAY_NAME:"):
            current_display = line.split(":", 1)[1].strip()
        elif line.startswith("STATE"):
            # STATE : 4 RUNNING
            match = re.search(r"\d+\s+(\w+)", line)
            current_state = match.group(1) if match else "UNKNOWN"
            if current_name:
                services.append(ServiceInfo(
                    name=current_name,
                    display_name=current_display,
                    state=current_state,
                ))
                current_name = ""

    return services


async def get_service_status(name: str) -> str:
    """Get status of a specific service."""
    output, rc = await _run_cmd(["sc", "query", name])
    return output


async def start_service(name: str) -> str:
    """Start a Windows service."""
    output, rc = await _run_cmd(["net", "start", name])
    return output.strip()


async def stop_service(name: str) -> str:
    """Stop a Windows service."""
    output, rc = await _run_cmd(["net", "stop", name])
    return output.strip()
