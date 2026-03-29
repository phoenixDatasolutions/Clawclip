"""MCP Registry — tracks connected MCP servers and their advertised tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class MCPServerInfo:
    """Metadata about a connected MCP server."""

    url: str
    name: str
    description: str = ""
    tools: list[dict] = field(default_factory=list)
    healthy: bool = True
    last_checked: datetime = field(default_factory=_utcnow)


class MCPRegistry:
    """Registry of known MCP servers and their tools.

    Provides a single place to look up all available MCP servers and
    aggregate the tools they expose. Health checks can be triggered to
    mark servers as unavailable.
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerInfo] = {}

    # ── CRUD ────────────────────────────────────────────────────────

    def register_server(self, info: MCPServerInfo) -> None:
        """Register (or update) an MCP server entry."""
        self._servers[info.url] = info
        logger.info("MCP server registered: %s (%s)", info.name, info.url)

    def unregister_server(self, url: str) -> None:
        """Remove an MCP server from the registry."""
        if url in self._servers:
            name = self._servers[url].name
            del self._servers[url]
            logger.info("MCP server unregistered: %s (%s)", name, url)

    def get_server(self, url: str) -> MCPServerInfo | None:
        """Return server info for the given URL, or None if not found."""
        return self._servers.get(url)

    def list_servers(self) -> list[MCPServerInfo]:
        """Return all registered servers."""
        return list(self._servers.values())

    # ── Tool aggregation ────────────────────────────────────────────

    def get_all_tools(self) -> list[dict]:
        """Aggregate tool definitions from all healthy servers."""
        tools: list[dict] = []
        for server in self._servers.values():
            if server.healthy:
                tools.extend(server.tools)
        return tools

    # ── Health checks ───────────────────────────────────────────────

    async def health_check_all(self) -> None:
        """Ping each registered server's /health endpoint.

        Updates the ``healthy`` and ``last_checked`` fields in-place.
        Requires httpx; silently skips health checks if not installed.
        """
        if not _HTTPX_AVAILABLE:
            logger.warning("httpx not installed — skipping MCP health checks")
            return

        import httpx  # noqa: PLC0415 — guarded above

        async with httpx.AsyncClient(timeout=5.0) as client:
            for server in self._servers.values():
                try:
                    resp = await client.get(f"{server.url.rstrip('/')}/health")
                    server.healthy = resp.status_code == 200
                except Exception as exc:
                    logger.warning("Health check failed for %s: %s", server.url, exc)
                    server.healthy = False
                finally:
                    server.last_checked = _utcnow()
