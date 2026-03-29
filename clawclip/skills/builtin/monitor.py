"""System Monitor Skill — CPU, RAM, disk, network, and process management."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


class SystemMonitorSkill:
    """Monitor system resources and manage processes via psutil."""

    @property
    def name(self) -> str:
        return "system_monitor"

    @property
    def description(self) -> str:
        return "Monitor CPU, RAM, disk, network, and processes"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="get_system_info",
                description="Get CPU, RAM, and uptime statistics",
                parameters={"type": "object", "properties": {}},
                required_permissions=["system.read"],
            ),
            ToolDefinition(
                name="get_process_list",
                description="List running processes sorted by CPU or memory usage",
                parameters={
                    "type": "object",
                    "properties": {
                        "sort_by": {"type": "string", "enum": ["cpu", "memory"], "default": "cpu"},
                        "limit": {"type": "integer", "description": "Max processes to return", "default": 20},
                    },
                },
                required_permissions=["system.read"],
            ),
            ToolDefinition(
                name="kill_process",
                description="Kill a process by PID",
                parameters={
                    "type": "object",
                    "properties": {
                        "pid": {"type": "integer", "description": "Process ID"},
                    },
                    "required": ["pid"],
                },
                required_permissions=["system.read"],
            ),
            ToolDefinition(
                name="get_disk_usage",
                description="Get disk usage for all mounted partitions",
                parameters={"type": "object", "properties": {}},
                required_permissions=["system.read"],
            ),
            ToolDefinition(
                name="get_network_stats",
                description="Get network I/O statistics per interface",
                parameters={"type": "object", "properties": {}},
                required_permissions=["system.read"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/monitor", "/top", "/ps"]

    @property
    def required_permissions(self) -> list[str]:
        return ["system.read"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        if not _PSUTIL_AVAILABLE:
            return SkillResult(success=False, output="psutil is not installed", error="missing dependency")

        if tool_name == "get_system_info":
            return await self._get_system_info()
        if tool_name == "get_process_list":
            return await self._get_process_list(arguments)
        if tool_name == "kill_process":
            return await self._kill_process(arguments)
        if tool_name == "get_disk_usage":
            return await self._get_disk_usage()
        if tool_name == "get_network_stats":
            return await self._get_network_stats()

        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        if trigger == "/ps":
            return await self.execute("get_process_list", {}, context)
        if trigger == "/top":
            return await self.execute("get_process_list", {"sort_by": "cpu", "limit": 15}, context)
        return await self.execute("get_system_info", {}, context)

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _get_system_info(self) -> SkillResult:
        def _collect() -> str:
            import platform
            import socket
            from datetime import datetime, timezone

            cpu_percent = psutil.cpu_percent(interval=0.5)
            cpu_count = psutil.cpu_count()
            mem = psutil.virtual_memory()
            boot = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
            uptime = datetime.now(timezone.utc) - boot
            hours, rem = divmod(int(uptime.total_seconds()), 3600)
            minutes, _ = divmod(rem, 60)

            lines = [
                f"Host: {socket.gethostname()} ({platform.system()} {platform.release()})",
                f"CPU: {cpu_percent}% ({cpu_count} logical cores)",
                f"RAM: {mem.used / 1024**3:.1f} GB / {mem.total / 1024**3:.1f} GB ({mem.percent}%)",
                f"Uptime: {hours}h {minutes}m",
            ]
            return "\n".join(lines)

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _collect)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _get_process_list(self, args: dict[str, Any]) -> SkillResult:
        sort_by = args.get("sort_by", "cpu")
        limit = int(args.get("limit", 20))

        def _collect() -> str:
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
                try:
                    info = p.info
                    mem_mb = (info["memory_info"].rss / 1024**2) if info.get("memory_info") else 0.0
                    procs.append({
                        "pid": info["pid"],
                        "name": info["name"] or "unknown",
                        "cpu": info.get("cpu_percent", 0) or 0.0,
                        "mem_mb": round(mem_mb, 1),
                        "status": info.get("status", "?"),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            key = "cpu" if sort_by == "cpu" else "mem_mb"
            procs.sort(key=lambda p: p[key], reverse=True)
            procs = procs[:limit]

            header = f"{'PID':>7}  {'CPU%':>6}  {'MEM MB':>8}  {'STATUS':<10}  NAME"
            rows = [header, "-" * 60]
            for p in procs:
                rows.append(f"{p['pid']:>7}  {p['cpu']:>6.1f}  {p['mem_mb']:>8.1f}  {p['status']:<10}  {p['name']}")
            return "\n".join(rows)

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _collect)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _kill_process(self, args: dict[str, Any]) -> SkillResult:
        pid = args.get("pid")
        if pid is None:
            return SkillResult(success=False, output="pid is required")

        def _do_kill() -> str:
            p = psutil.Process(int(pid))
            name = p.name()
            p.kill()
            return f"Killed process {pid} ({name})"

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _do_kill)
            return SkillResult(success=True, output=output)
        except psutil.NoSuchProcess:
            return SkillResult(success=False, output=f"Process {pid} not found")
        except psutil.AccessDenied:
            return SkillResult(success=False, output=f"Access denied for process {pid}")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _get_disk_usage(self) -> SkillResult:
        def _collect() -> str:
            lines = [f"{'Mount':<20}  {'Total GB':>10}  {'Used GB':>9}  {'Free GB':>9}  {'Use%':>5}"]
            lines.append("-" * 60)
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    lines.append(
                        f"{part.mountpoint:<20}  "
                        f"{usage.total / 1024**3:>10.1f}  "
                        f"{usage.used / 1024**3:>9.1f}  "
                        f"{usage.free / 1024**3:>9.1f}  "
                        f"{usage.percent:>4.1f}%"
                    )
                except (PermissionError, OSError):
                    lines.append(f"{part.mountpoint:<20}  (inaccessible)")
            return "\n".join(lines)

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _collect)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _get_network_stats(self) -> SkillResult:
        def _collect() -> str:
            counters = psutil.net_io_counters(pernic=True)
            lines = [f"{'Interface':<16}  {'Sent MB':>9}  {'Recv MB':>9}  {'Pkts Sent':>11}  {'Pkts Recv':>11}"]
            lines.append("-" * 65)
            for iface, stats in counters.items():
                lines.append(
                    f"{iface:<16}  "
                    f"{stats.bytes_sent / 1024**2:>9.1f}  "
                    f"{stats.bytes_recv / 1024**2:>9.1f}  "
                    f"{stats.packets_sent:>11}  "
                    f"{stats.packets_recv:>11}"
                )
            return "\n".join(lines) if len(lines) > 2 else "No network interfaces found"

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _collect)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))


def create_skill(config: dict) -> SystemMonitorSkill:
    return SystemMonitorSkill()
