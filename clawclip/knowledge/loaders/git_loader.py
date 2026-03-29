"""Git repository loader for the ClawClip RAG Knowledge Base module.

Indexes the text files tracked by a git repository using ``git ls-files``.
Only files whose paths match at least one of the *include_patterns* are
included.  Metadata records the active branch, the HEAD commit hash, and the
file's last-modified timestamp on disk.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def _run_git(args: list[str], cwd: str) -> str:
    """Run a git sub-command asynchronously and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")
    return stdout.decode("utf-8", errors="replace")


async def _get_branch(repo_path: str) -> str:
    try:
        output = await _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
        return output.strip()
    except Exception:
        return "unknown"


async def _get_commit_hash(repo_path: str) -> str:
    try:
        output = await _run_git(["rev-parse", "HEAD"], cwd=repo_path)
        return output.strip()
    except Exception:
        return "unknown"


def _matches_any(path: str, patterns: list[str]) -> bool:
    name = os.path.basename(path)
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(path, pattern):
            return True
    return False


async def load_repo(
    repo_path: str,
    include_patterns: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Index a git repository's tracked files.

    Parameters
    ----------
    repo_path:
        Absolute (or relative) path to the root of the git repository.
    include_patterns:
        List of shell glob patterns used to filter files.  Matched against
        both the full relative path and the filename.
        Defaults to ``["*.py", "*.md", "*.ts"]``.

    Returns
    -------
    list of ``{content: str, metadata: dict}``
    """
    if include_patterns is None:
        include_patterns = ["*.py", "*.md", "*.ts"]

    root = Path(repo_path).resolve()
    if not root.is_dir():
        logger.error("load_repo: not a directory: %s", repo_path)
        return []

    # Gather git metadata upfront (both tasks run concurrently).
    branch, commit_hash = await asyncio.gather(
        _get_branch(str(root)),
        _get_commit_hash(str(root)),
    )
    logger.info(
        "load_repo: branch=%s commit=%s root=%s", branch, commit_hash[:8], root
    )

    # Get the list of tracked files.
    try:
        ls_output = await _run_git(["ls-files"], cwd=str(root))
    except RuntimeError as exc:
        logger.error("load_repo: failed to list files: %s", exc)
        return []

    all_files = [line.strip() for line in ls_output.splitlines() if line.strip()]
    matched = [f for f in all_files if _matches_any(f, include_patterns)]
    logger.info("load_repo: %d/%d files matched", len(matched), len(all_files))

    documents: list[dict[str, Any]] = []
    for rel_path in matched:
        abs_path = root / rel_path
        if not abs_path.is_file():
            continue
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("load_repo: could not read %s: %s", rel_path, exc)
            continue
        if not content.strip():
            continue
        stat = abs_path.stat()
        metadata: dict[str, Any] = {
            "file_path": str(abs_path),
            "source": str(abs_path),
            "git_branch": branch,
            "commit_hash": commit_hash,
            "last_modified": stat.st_mtime,
            "repo_root": str(root),
            "relative_path": rel_path,
        }
        documents.append({"content": content, "metadata": metadata})

    logger.info("load_repo: loaded %d documents from %s", len(documents), root)
    return documents
