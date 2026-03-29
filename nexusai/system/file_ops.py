"""File system operations with path validation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nexusai.utils.security import is_sensitive_file, validate_path


@dataclass
class FileInfo:
    name: str
    is_dir: bool
    size: int
    modified_at: datetime


def _list_dir(path_str: str) -> list[FileInfo]:
    """Synchronous directory listing."""
    resolved = validate_path(path_str)
    if not resolved.is_dir():
        raise ValueError(f"Not a directory: {resolved}")

    entries = []
    for child in sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        try:
            stat = child.stat()
            entries.append(FileInfo(
                name=child.name,
                is_dir=child.is_dir(),
                size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            ))
        except (PermissionError, OSError):
            continue
    return entries


def _read_file(path_str: str, limit_lines: int = 200) -> str:
    """Synchronous file read with line limit."""
    resolved = validate_path(path_str)
    if not resolved.is_file():
        raise ValueError(f"Not a file: {resolved}")
    if is_sensitive_file(resolved.name):
        raise ValueError(f"Cannot read sensitive file: {resolved.name}")

    lines = []
    with open(resolved, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i >= limit_lines:
                lines.append(f"\n... (showing first {limit_lines} lines)")
                break
            lines.append(line)
    return "".join(lines)


async def list_dir(path_str: str) -> list[FileInfo]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _list_dir, path_str)


async def read_file(path_str: str, limit_lines: int = 200) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _read_file, path_str, limit_lines)


async def get_file_for_download(path_str: str) -> Path:
    """Validate path and return resolved Path for download."""
    resolved = validate_path(path_str)
    if not resolved.is_file():
        raise ValueError(f"Not a file: {resolved}")
    return resolved


async def save_uploaded_file(file_bytes: bytes, dest_path: str) -> Path:
    """Save uploaded bytes to a validated destination."""
    resolved = validate_path(dest_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    def _write():
        with open(resolved, "wb") as f:
            f.write(file_bytes)
        return resolved

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _write)
