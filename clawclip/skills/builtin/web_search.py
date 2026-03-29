"""Web Search Skill — search the web and fetch URLs via Tavily, SerpAPI, or DuckDuckGo."""

from __future__ import annotations

import logging
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


class WebSearchSkill:
    """Web search and URL fetching with multiple provider fallback."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the web and fetch URLs (Tavily / SerpAPI / DuckDuckGo)"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="web_search",
                description="Search the web for a query and return top results",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Maximum results", "default": 5},
                    },
                    "required": ["query"],
                },
                required_permissions=["web.search"],
            ),
            ToolDefinition(
                name="fetch_url",
                description="Fetch the content of a URL and return its text",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"},
                        "timeout": {"type": "integer", "description": "Request timeout in seconds", "default": 15},
                    },
                    "required": ["url"],
                },
                required_permissions=["web.search"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/search", "/web"]

    @property
    def required_permissions(self) -> list[str]:
        return ["web.search"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        if not _HTTPX_AVAILABLE:
            return SkillResult(success=False, output="httpx is not installed", error="missing dependency")

        if tool_name == "web_search":
            return await self._web_search(arguments, context.config)
        if tool_name == "fetch_url":
            return await self._fetch_url(arguments)

        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        if not args.strip():
            return SkillResult(success=False, output=f"Usage: {trigger} <query>")
        return await self.execute("web_search", {"query": args.strip()}, context)

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _web_search(self, args: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        query = args.get("query", "")
        max_results = int(args.get("max_results", 5))
        provider = config.get("provider", "duckduckgo")
        api_key = config.get("api_key", "")

        if not query:
            return SkillResult(success=False, output="query is required")

        if provider == "tavily" and api_key:
            return await self._search_tavily(query, max_results, api_key)
        elif provider == "serpapi" and api_key:
            return await self._search_serpapi(query, max_results, api_key)
        else:
            return await self._search_duckduckgo(query, max_results)

    async def _search_tavily(self, query: str, max_results: int, api_key: str) -> SkillResult:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": api_key, "query": query, "max_results": max_results},
                )
                response.raise_for_status()
                data = response.json()

            results = data.get("results", [])
            lines = [f"Tavily results for: {query}\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r.get('title', 'No title')}")
                lines.append(f"   {r.get('url', '')}")
                if r.get("content"):
                    snippet = r["content"][:200].replace("\n", " ")
                    lines.append(f"   {snippet}...")
                lines.append("")
            return SkillResult(success=True, output="\n".join(lines).strip())
        except Exception as e:
            logger.warning("Tavily search failed: %s, falling back to DuckDuckGo", e)
            return await self._search_duckduckgo(query, max_results)

    async def _search_serpapi(self, query: str, max_results: int, api_key: str) -> SkillResult:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    "https://serpapi.com/search",
                    params={"q": query, "api_key": api_key, "num": max_results},
                )
                response.raise_for_status()
                data = response.json()

            results = data.get("organic_results", [])
            lines = [f"SerpAPI results for: {query}\n"]
            for i, r in enumerate(results[:max_results], 1):
                lines.append(f"{i}. {r.get('title', 'No title')}")
                lines.append(f"   {r.get('link', '')}")
                if r.get("snippet"):
                    lines.append(f"   {r['snippet'][:200]}")
                lines.append("")
            return SkillResult(success=True, output="\n".join(lines).strip())
        except Exception as e:
            logger.warning("SerpAPI search failed: %s, falling back to DuckDuckGo", e)
            return await self._search_duckduckgo(query, max_results)

    async def _search_duckduckgo(self, query: str, max_results: int) -> SkillResult:
        try:
            async with httpx.AsyncClient(
                timeout=20,
                headers={"User-Agent": "ClawClip/1.0"},
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                )
                response.raise_for_status()
                data = response.json()

            lines = [f"DuckDuckGo results for: {query}\n"]

            if data.get("AbstractText"):
                lines.append(f"Summary: {data['AbstractText'][:400]}")
                if data.get("AbstractURL"):
                    lines.append(f"Source: {data['AbstractURL']}")
                lines.append("")

            related = data.get("RelatedTopics", [])[:max_results]
            for i, r in enumerate(related, 1):
                if isinstance(r, dict) and r.get("Text"):
                    lines.append(f"{i}. {r['Text'][:200]}")
                    if r.get("FirstURL"):
                        lines.append(f"   {r['FirstURL']}")
                    lines.append("")

            output = "\n".join(lines).strip()
            if not output or output == f"DuckDuckGo results for: {query}":
                output = f"No results found for: {query}"
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=f"Search failed: {e}", error=str(e))

    async def _fetch_url(self, args: dict[str, Any]) -> SkillResult:
        url = args.get("url", "")
        timeout = int(args.get("timeout", 15))

        if not url:
            return SkillResult(success=False, output="url is required")

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                headers={"User-Agent": "ClawClip/1.0"},
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "text" in content_type or "json" in content_type:
                text = response.text[:10_000]
                if len(response.text) > 10_000:
                    text += "\n... (truncated)"
                return SkillResult(
                    success=True,
                    output=f"URL: {url}\nStatus: {response.status_code}\n\n{text}",
                )
            else:
                return SkillResult(
                    success=True,
                    output=f"URL: {url}\nStatus: {response.status_code}\nContent-Type: {content_type}\n(binary content, not shown)",
                )
        except Exception as e:
            return SkillResult(success=False, output=f"Failed to fetch {url}: {e}", error=str(e))


def create_skill(config: dict) -> WebSearchSkill:
    return WebSearchSkill()
