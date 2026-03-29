"""Log Analysis Skill — tail, search, parse errors, and summarize log files."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

_ERROR_PATTERNS = [
    re.compile(r"\b(ERROR|CRITICAL|FATAL|EXCEPTION|TRACEBACK)\b", re.IGNORECASE),
    re.compile(r"(?i)error\s*:", ),
    re.compile(r"(?i)exception\s*:"),
]


class LogAnalysisSkill:
    """Read and analyze log files — tail, grep, parse errors, summarize."""

    @property
    def name(self) -> str:
        return "log_analysis"

    @property
    def description(self) -> str:
        return "Tail, search, parse errors, and summarize log files"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="tail_log",
                description="Read the last N lines of a log file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Log file path"},
                        "lines": {"type": "integer", "description": "Number of lines to read from end", "default": 50},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.read"],
            ),
            ToolDefinition(
                name="search_log",
                description="Search a log file for lines matching a pattern",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Log file path"},
                        "pattern": {"type": "string", "description": "Regex or plain text pattern to search"},
                        "max_matches": {"type": "integer", "description": "Maximum matching lines to return", "default": 50},
                        "context_lines": {"type": "integer", "description": "Lines of context around each match", "default": 0},
                    },
                    "required": ["path", "pattern"],
                },
                required_permissions=["files.read"],
            ),
            ToolDefinition(
                name="parse_error_log",
                description="Extract all error/exception lines from a log file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Log file path"},
                        "max_errors": {"type": "integer", "description": "Maximum errors to return", "default": 30},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.read"],
            ),
            ToolDefinition(
                name="get_log_summary",
                description="Summarize a log file: line count, error count, common patterns",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Log file path"},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.read"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/log", "/logs"]

    @property
    def required_permissions(self) -> list[str]:
        return ["files.read"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        if tool_name == "tail_log":
            return await self._tail_log(arguments)
        if tool_name == "search_log":
            return await self._search_log(arguments)
        if tool_name == "parse_error_log":
            return await self._parse_error_log(arguments)
        if tool_name == "get_log_summary":
            return await self._get_log_summary(arguments)
        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        parts = args.strip().split(maxsplit=1)
        if not parts:
            return SkillResult(success=False, output="Usage: /log <path> [search <pattern>|errors|summary]")

        path = parts[0]
        subcmd = parts[1].strip() if len(parts) > 1 else "tail"

        if subcmd.startswith("search "):
            pattern = subcmd[7:].strip()
            return await self.execute("search_log", {"path": path, "pattern": pattern}, context)
        if subcmd == "errors":
            return await self.execute("parse_error_log", {"path": path}, context)
        if subcmd == "summary":
            return await self.execute("get_log_summary", {"path": path}, context)
        return await self.execute("tail_log", {"path": path}, context)

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _read_lines(self, path_str: str) -> list[str] | SkillResult:
        resolved = Path(path_str).resolve()

        def _do_read() -> list[str]:
            if not resolved.is_file():
                raise ValueError(f"Not a file: {resolved}")
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                return f.readlines()

        try:
            return await asyncio.get_event_loop().run_in_executor(None, _do_read)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _tail_log(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")
        n = int(args.get("lines", 50))

        result = await self._read_lines(path_str)
        if isinstance(result, SkillResult):
            return result

        tail = result[-n:]
        return SkillResult(success=True, output="".join(tail).rstrip() or "(empty file)")

    async def _search_log(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")
        pattern = args.get("pattern", "")
        max_matches = int(args.get("max_matches", 50))
        context_lines = int(args.get("context_lines", 0))

        if not pattern:
            return SkillResult(success=False, output="pattern is required")

        result = await self._read_lines(path_str)
        if isinstance(result, SkillResult):
            return result

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return SkillResult(success=False, output=f"Invalid regex pattern: {e}")

        matches: list[str] = []
        for i, line in enumerate(result):
            if regex.search(line):
                start = max(0, i - context_lines)
                end = min(len(result), i + context_lines + 1)
                block = [f"  {result[j].rstrip()}" for j in range(start, end) if j != i]
                matches.append(f"Line {i + 1}: {line.rstrip()}")
                matches.extend(block)
                if len(matches) >= max_matches:
                    matches.append(f"... (limited to {max_matches} matches)")
                    break

        if not matches:
            return SkillResult(success=True, output=f"No matches for '{pattern}' in {path_str}")
        return SkillResult(success=True, output="\n".join(matches))

    async def _parse_error_log(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")
        max_errors = int(args.get("max_errors", 30))

        result = await self._read_lines(path_str)
        if isinstance(result, SkillResult):
            return result

        errors: list[str] = []
        for i, line in enumerate(result, 1):
            if any(p.search(line) for p in _ERROR_PATTERNS):
                errors.append(f"Line {i}: {line.rstrip()}")
                if len(errors) >= max_errors:
                    errors.append(f"... (limited to {max_errors} errors)")
                    break

        if not errors:
            return SkillResult(success=True, output=f"No errors found in {path_str}")
        return SkillResult(
            success=True,
            output=f"Found {len(errors)} error(s) in {path_str}:\n\n" + "\n".join(errors),
        )

    async def _get_log_summary(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")

        result = await self._read_lines(path_str)
        if isinstance(result, SkillResult):
            return result

        total_lines = len(result)
        error_count = sum(1 for line in result if any(p.search(line) for p in _ERROR_PATTERNS))

        level_pattern = re.compile(r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b", re.IGNORECASE)
        level_counter: Counter = Counter()
        for line in result:
            match = level_pattern.search(line)
            if match:
                level_counter[match.group(1).upper()] += 1

        summary_lines = [
            f"Log summary: {path_str}",
            f"Total lines: {total_lines}",
            f"Error lines: {error_count}",
        ]
        if level_counter:
            summary_lines.append("Log levels:")
            for level, count in sorted(level_counter.items(), key=lambda x: -x[1]):
                summary_lines.append(f"  {level}: {count}")

        return SkillResult(success=True, output="\n".join(summary_lines))


def create_skill(config: dict) -> LogAnalysisSkill:
    return LogAnalysisSkill()
