"""File and directory loaders for the ClawClip RAG Knowledge Base module.

Reads local files into the ``{content: str, metadata: dict}`` format expected
by :class:`~clawclip.knowledge.indexer.DocumentIndexer`.

Supported formats (built-in): .txt, .md, .py, .js, .ts, .yaml, .yml,
.json, .csv, .html

Optional formats (graceful fallback if library not installed):
- .pdf  — uses ``pypdf`` if available
- .docx — uses ``python-docx`` if available
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Optional deps ─────────────────────────────────────────────────

try:
    import pypdf as _pypdf
    _HAS_PYPDF = True
except ImportError:
    _HAS_PYPDF = False

try:
    import docx as _docx  # python-docx
    _HAS_DOCX = True
except ImportError:
    _HAS_DOCX = False

# ── Constants ─────────────────────────────────────────────────────

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".yaml", ".yml", ".json", ".csv", ".html", ".htm",
    ".sh", ".bash", ".toml", ".ini", ".cfg", ".rst",
    ".xml", ".sql", ".go", ".rs", ".java", ".c", ".cpp",
    ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
}


# ── Helpers ───────────────────────────────────────────────────────


def _build_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "file_path": str(path.resolve()),
        "file_type": path.suffix.lower(),
        "file_size": stat.st_size,
        "last_modified": stat.st_mtime,
        "source": str(path.resolve()),
    }


def _load_pdf(path: Path) -> str:
    if _HAS_PYPDF:
        reader = _pypdf.PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    # Fallback: read raw bytes and extract printable ASCII
    logger.warning(
        "pypdf not installed — falling back to raw text extraction for %s", path
    )
    raw = path.read_bytes()
    printable = "".join(chr(b) for b in raw if 32 <= b < 127 or b in (9, 10, 13))
    return printable


def _load_docx(path: Path) -> str:
    if _HAS_DOCX:
        doc = _docx.Document(str(path))
        return "\n\n".join(para.text for para in doc.paragraphs if para.text.strip())
    logger.warning(
        "python-docx not installed — falling back to raw text extraction for %s", path
    )
    raw = path.read_bytes()
    printable = "".join(chr(b) for b in raw if 32 <= b < 127 or b in (9, 10, 13))
    return printable


def _load_csv(path: Path) -> str:
    """Convert CSV to a readable text representation."""
    rows: list[list[str]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)
    if not rows:
        return ""
    lines = [", ".join(row) for row in rows]
    return "\n".join(lines)


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_content(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix == ".docx":
        return _load_docx(path)
    if suffix == ".csv":
        return _load_csv(path)
    # All other recognised text formats
    return _load_text(path)


# ── Public API ────────────────────────────────────────────────────


async def load_file(path: str) -> list[dict[str, Any]]:
    """Load a single file and return a list with one document dict.

    Returns
    -------
    list of ``{content: str, metadata: dict}``
    """
    p = Path(path)
    if not p.exists():
        logger.error("File not found: %s", path)
        return []
    if not p.is_file():
        logger.error("Path is not a file: %s", path)
        return []

    suffix = p.suffix.lower()
    if suffix not in _TEXT_EXTENSIONS and suffix not in (".pdf", ".docx"):
        logger.warning("Unsupported file type %s — attempting plain text read", suffix)

    try:
        content = _extract_content(p)
    except Exception as exc:
        logger.error("Failed to read %s: %s", path, exc)
        return []

    if not content.strip():
        logger.debug("Empty content from %s — skipping", path)
        return []

    return [{"content": content, "metadata": _build_metadata(p)}]


async def load_directory(
    path: str,
    glob_pattern: str = "**/*",
) -> list[dict[str, Any]]:
    """Recursively load all supported files under *path*.

    Parameters
    ----------
    path:
        Root directory to scan.
    glob_pattern:
        Glob pattern relative to *path* (default ``**/*`` — all files).

    Returns
    -------
    list of ``{content: str, metadata: dict}``
    """
    root = Path(path)
    if not root.is_dir():
        logger.error("Path is not a directory: %s", path)
        return []

    documents: list[dict[str, Any]] = []
    matched = list(root.glob(glob_pattern))
    logger.info("load_directory: %d paths matched in %s", len(matched), path)

    for p in matched:
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix not in _TEXT_EXTENSIONS and suffix not in (".pdf", ".docx"):
            continue
        docs = await load_file(str(p))
        documents.extend(docs)

    logger.info("load_directory: loaded %d documents from %s", len(documents), path)
    return documents
