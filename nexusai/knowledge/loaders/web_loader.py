"""Web page loader for the NexusAI RAG Knowledge Base module.

Fetches HTML pages with ``httpx`` and extracts human-readable text by parsing
the relevant structural tags (headings, paragraphs, list items).  No heavy
parser dependency — the extraction is done with a small hand-written state
machine that strips tags and normalises whitespace.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

try:
    import httpx as _httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


# ── HTML extraction helpers ───────────────────────────────────────

# Tags whose text content we want to keep.
_KEEP_TAGS = frozenset([
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "blockquote", "pre", "code",
    "article", "section", "main",
])

_TAG_RE = re.compile(r"<([/!]?[a-zA-Z][a-zA-Z0-9]*)[^>]*>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _strip_head(html: str) -> str:
    """Remove everything inside <head>...</head>."""
    return re.sub(r"(?is)<head[^>]*>.*?</head>", "", html)


def _strip_script_style(html: str) -> str:
    """Remove <script> and <style> blocks entirely."""
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", "", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", "", html)
    return html


def _extract_title(html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return m.group(1).strip() if m else ""


def _html_to_text(html: str) -> str:
    """
    Lightweight tag-aware text extractor.

    Inserts newlines around block-level / heading tags so paragraphs stay
    separated, then strips all remaining tags.
    """
    html = _strip_head(html)
    html = _strip_script_style(html)

    # Insert newlines around block tags we care about.
    block_re = re.compile(
        r"<(/?)(?:p|h[1-6]|li|td|th|tr|div|article|section|main|blockquote|pre)[^>]*>",
        re.IGNORECASE,
    )
    html = block_re.sub(r"\n", html)

    # Decode common HTML entities.
    html = html.replace("&amp;", "&")
    html = html.replace("&lt;", "<")
    html = html.replace("&gt;", ">")
    html = html.replace("&nbsp;", " ")
    html = html.replace("&quot;", '"')
    html = html.replace("&#39;", "'")
    html = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), html)

    # Strip all remaining tags.
    html = re.sub(r"<[^>]+>", "", html)

    # Normalise whitespace.
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in html.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


# ── Public API ────────────────────────────────────────────────────


async def load_url(url: str) -> dict[str, Any]:
    """Fetch *url* and return ``{content: str, metadata: dict}``.

    Returns an empty dict on failure (logs the error).
    """
    if not _HAS_HTTPX:
        raise ImportError(
            "httpx package is required for WebLoader. "
            "Install it with: pip install httpx"
        )

    logger.info("load_url: fetching %s", url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; NexusAI-WebLoader/1.0; "
            "+https://github.com/nexusai)"
        )
    }
    try:
        async with _httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers=headers,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except Exception as exc:
        logger.error("load_url: failed to fetch %s: %s", url, exc)
        return {}

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        logger.warning(
            "load_url: unexpected content-type %r for %s", content_type, url
        )

    html = response.text
    title = _extract_title(html)
    text = _html_to_text(html)

    if not text.strip():
        logger.warning("load_url: extracted empty content from %s", url)
        return {}

    metadata: dict[str, Any] = {
        "url": url,
        "title": title,
        "source": url,
        "content_type": content_type,
        "status_code": response.status_code,
        "final_url": str(response.url),
    }
    return {"content": text, "metadata": metadata}


async def load_urls(urls: list[str]) -> list[dict[str, Any]]:
    """Fetch multiple URLs concurrently and return all non-empty results.

    Parameters
    ----------
    urls:
        List of URLs to fetch.

    Returns
    -------
    list of ``{content: str, metadata: dict}``
    """
    import asyncio

    if not urls:
        return []

    results = await asyncio.gather(*(load_url(u) for u in urls), return_exceptions=True)
    documents: list[dict[str, Any]] = []
    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            logger.error("load_urls: error fetching %s: %s", url, result)
            continue
        if result:
            documents.append(result)

    logger.info("load_urls: %d/%d URLs loaded successfully", len(documents), len(urls))
    return documents
