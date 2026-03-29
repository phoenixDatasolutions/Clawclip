"""File Skill — read, write, and manage files on the local filesystem."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from nexusai.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

_ALLOWED_ROOTS: list[str] = []  # empty = no restriction; populated via config


def _resolve_safe(path_str: str, allowed_roots: list[str]) -> Path | None:
    """Resolve a path and check it does not escape allowed roots."""
    try:
        resolved = Path(path_str).resolve()
    except Exception:
        return None
    if not allowed_roots:
        return resolved
    for root in allowed_roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return resolved
        except ValueError:
            continue
    return None


class FileSkill:
    """Read, write, list, delete, copy, move, and search files."""

    @property
    def name(self) -> str:
        return "files"

    @property
    def description(self) -> str:
        return "Manage local files — read, write, list, delete, copy, move, search"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="read_file",
                description="Read the contents of a file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute or relative file path"},
                        "limit_lines": {"type": "integer", "description": "Max lines to read", "default": 200},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.read"],
            ),
            ToolDefinition(
                name="write_file",
                description="Write content to a file (creates or overwrites)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to write"},
                        "content": {"type": "string", "description": "Content to write"},
                        "append": {"type": "boolean", "description": "Append instead of overwrite", "default": False},
                    },
                    "required": ["path", "content"],
                },
                required_permissions=["files.write"],
            ),
            ToolDefinition(
                name="list_directory",
                description="List files and directories in a path",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.read"],
            ),
            ToolDefinition(
                name="delete_file",
                description="Delete a file or empty directory",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to delete"},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.write"],
            ),
            ToolDefinition(
                name="copy_file",
                description="Copy a file to a destination path",
                parameters={
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "Source file path"},
                        "dst": {"type": "string", "description": "Destination file path"},
                    },
                    "required": ["src", "dst"],
                },
                required_permissions=["files.write"],
            ),
            ToolDefinition(
                name="move_file",
                description="Move or rename a file",
                parameters={
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "Source path"},
                        "dst": {"type": "string", "description": "Destination path"},
                    },
                    "required": ["src", "dst"],
                },
                required_permissions=["files.write"],
            ),
            ToolDefinition(
                name="search_files",
                description="Search for files matching a glob pattern under a directory",
                parameters={
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Root directory to search"},
                        "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py')"},
                        "max_results": {"type": "integer", "description": "Maximum results", "default": 50},
                    },
                    "required": ["directory", "pattern"],
                },
                required_permissions=["files.read"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/ls", "/cat", "/find"]

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
        allowed_roots: list[str] = context.config.get("allowed_roots", [])

        if tool_name == "read_file":
            return await self._read_file(arguments, allowed_roots)
        if tool_name == "write_file":
            return await self._write_file(arguments, allowed_roots)
        if tool_name == "list_directory":
            return await self._list_directory(arguments, allowed_roots)
        if tool_name == "delete_file":
            return await self._delete_file(arguments, allowed_roots)
        if tool_name == "copy_file":
            return await self._copy_file(arguments, allowed_roots)
        if tool_name == "move_file":
            return await self._move_file(arguments, allowed_roots)
        if tool_name == "search_files":
            return await self._search_files(arguments, allowed_roots)

        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        if trigger == "/ls":
            path = args.strip() or context.working_directory or "."
            return await self.execute("list_directory", {"path": path}, context)
        if trigger == "/cat":
            if not args.strip():
                return SkillResult(success=False, output="Usage: /cat <path>")
            return await self.execute("read_file", {"path": args.strip()}, context)
        if trigger == "/find":
            parts = args.strip().split(maxsplit=1)
            if len(parts) < 2:
                return SkillResult(success=False, output="Usage: /find <directory> <pattern>")
            return await self.execute("search_files", {"directory": parts[0], "pattern": parts[1]}, context)
        return SkillResult(success=False, output=f"Unknown trigger: {trigger}")

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _read_file(self, args: dict[str, Any], allowed_roots: list[str]) -> SkillResult:
        path_str = args.get("path", "")
        limit = int(args.get("limit_lines", 200))

        resolved = _resolve_safe(path_str, allowed_roots)
        if resolved is None:
            return SkillResult(success=False, output=f"Path not allowed or invalid: {path_str}")

        def _do_read() -> str:
            if not resolved.is_file():
                raise ValueError(f"Not a file: {resolved}")
            lines: list[str] = []
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= limit:
                        lines.append(f"\n... (truncated at {limit} lines)")
                        break
                    lines.append(line)
            return "".join(lines)

        try:
            content = await asyncio.get_event_loop().run_in_executor(None, _do_read)
            return SkillResult(success=True, output=content or "(empty file)")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _write_file(self, args: dict[str, Any], allowed_roots: list[str]) -> SkillResult:
        path_str = args.get("path", "")
        content = args.get("content", "")
        append = bool(args.get("append", False))

        resolved = _resolve_safe(path_str, allowed_roots)
        if resolved is None:
            return SkillResult(success=False, output=f"Path not allowed or invalid: {path_str}")

        def _do_write() -> None:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(resolved, mode, encoding="utf-8") as f:
                f.write(content)

        try:
            await asyncio.get_event_loop().run_in_executor(None, _do_write)
            action = "Appended to" if append else "Wrote"
            return SkillResult(success=True, output=f"{action} {resolved} ({len(content)} chars)")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _list_directory(self, args: dict[str, Any], allowed_roots: list[str]) -> SkillResult:
        path_str = args.get("path", ".")

        resolved = _resolve_safe(path_str, allowed_roots)
        if resolved is None:
            return SkillResult(success=False, output=f"Path not allowed or invalid: {path_str}")

        def _do_list() -> str:
            if not resolved.is_dir():
                raise ValueError(f"Not a directory: {resolved}")
            entries = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = []
            for entry in entries:
                try:
                    stat = entry.stat()
                    kind = "d" if entry.is_dir() else "f"
                    size = stat.st_size
                    lines.append(f"[{kind}] {entry.name}  ({size} bytes)")
                except (PermissionError, OSError):
                    lines.append(f"[?] {entry.name}  (inaccessible)")
            return "\n".join(lines) or "(empty directory)"

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _do_list)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _delete_file(self, args: dict[str, Any], allowed_roots: list[str]) -> SkillResult:
        path_str = args.get("path", "")

        resolved = _resolve_safe(path_str, allowed_roots)
        if resolved is None:
            return SkillResult(success=False, output=f"Path not allowed or invalid: {path_str}")

        def _do_delete() -> str:
            if resolved.is_dir():
                resolved.rmdir()
                return f"Deleted directory: {resolved}"
            elif resolved.is_file():
                resolved.unlink()
                return f"Deleted file: {resolved}"
            else:
                raise FileNotFoundError(f"Path not found: {resolved}")

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _do_delete)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _copy_file(self, args: dict[str, Any], allowed_roots: list[str]) -> SkillResult:
        src_str = args.get("src", "")
        dst_str = args.get("dst", "")

        src = _resolve_safe(src_str, allowed_roots)
        dst = _resolve_safe(dst_str, allowed_roots)

        if src is None:
            return SkillResult(success=False, output=f"Source path not allowed: {src_str}")
        if dst is None:
            return SkillResult(success=False, output=f"Destination path not allowed: {dst_str}")

        def _do_copy() -> str:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            return f"Copied {src} -> {dst}"

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _do_copy)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _move_file(self, args: dict[str, Any], allowed_roots: list[str]) -> SkillResult:
        src_str = args.get("src", "")
        dst_str = args.get("dst", "")

        src = _resolve_safe(src_str, allowed_roots)
        dst = _resolve_safe(dst_str, allowed_roots)

        if src is None:
            return SkillResult(success=False, output=f"Source path not allowed: {src_str}")
        if dst is None:
            return SkillResult(success=False, output=f"Destination path not allowed: {dst_str}")

        def _do_move() -> str:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return f"Moved {src} -> {dst}"

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _do_move)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _search_files(self, args: dict[str, Any], allowed_roots: list[str]) -> SkillResult:
        directory = args.get("directory", ".")
        pattern = args.get("pattern", "*")
        max_results = int(args.get("max_results", 50))

        resolved = _resolve_safe(directory, allowed_roots)
        if resolved is None:
            return SkillResult(success=False, output=f"Directory not allowed or invalid: {directory}")

        def _do_search() -> str:
            if not resolved.is_dir():
                raise ValueError(f"Not a directory: {resolved}")
            matches = []
            for match in resolved.rglob(pattern):
                matches.append(str(match))
                if len(matches) >= max_results:
                    break
            if not matches:
                return f"No files matching '{pattern}' in {resolved}"
            result = "\n".join(matches)
            if len(matches) == max_results:
                result += f"\n... (limited to {max_results} results)"
            return result

        try:
            output = await asyncio.get_event_loop().run_in_executor(None, _do_search)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))


def create_skill(config: dict) -> FileSkill:
    return FileSkill()
