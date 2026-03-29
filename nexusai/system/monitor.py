"""System monitoring via psutil — CPU, RAM, disk, processes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial

import psutil


@dataclass
class SystemInfo:
    hostname: str
    cpu_percent: float
    cpu_count: int
    ram_used_gb: float
    ram_total_gb: float
    ram_percent: float
    disks: list[dict]
    boot_time: datetime
    uptime_str: str


@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float
    status: str


def _get_system_info() -> SystemInfo:
    """Synchronous system info collection."""
    import platform
    import socket

    cpu_percent = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    boot = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
    now = datetime.now(timezone.utc)
    uptime = now - boot

    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m"

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "mount": part.mountpoint,
                "total_gb": round(usage.total / (1024**3), 1),
                "used_gb": round(usage.used / (1024**3), 1),
                "percent": usage.percent,
            })
        except PermissionError:
            continue

    return SystemInfo(
        hostname=socket.gethostname(),
        cpu_percent=cpu_percent,
        cpu_count=psutil.cpu_count(),
        ram_used_gb=round(mem.used / (1024**3), 1),
        ram_total_gb=round(mem.total / (1024**3), 1),
        ram_percent=mem.percent,
        disks=disks,
        boot_time=boot,
        uptime_str=uptime_str,
    )


def _get_processes(sort_by: str = "cpu", limit: int = 15) -> list[ProcessInfo]:
    """Synchronous process listing."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
        try:
            info = p.info
            mem_mb = (info["memory_info"].rss / (1024**2)) if info.get("memory_info") else 0
            procs.append(ProcessInfo(
                pid=info["pid"],
                name=info["name"] or "unknown",
                cpu_percent=info.get("cpu_percent", 0) or 0,
                memory_mb=round(mem_mb, 1),
                status=info.get("status", "unknown"),
            ))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    key = "cpu_percent" if sort_by == "cpu" else "memory_mb"
    procs.sort(key=lambda p: getattr(p, key), reverse=True)
    return procs[:limit]


async def get_system_info() -> SystemInfo:
    """Async wrapper for system info collection."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_system_info)


async def get_processes(sort_by: str = "cpu", limit: int = 15) -> list[ProcessInfo]:
    """Async wrapper for process listing."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_get_processes, sort_by, limit))


async def kill_process(pid: int) -> str:
    """Kill a process by PID. Returns status message."""
    try:
        p = psutil.Process(pid)
        name = p.name()
        p.kill()
        return f"Killed process {pid} ({name})"
    except psutil.NoSuchProcess:
        return f"Process {pid} not found"
    except psutil.AccessDenied:
        return f"Access denied for process {pid}"
