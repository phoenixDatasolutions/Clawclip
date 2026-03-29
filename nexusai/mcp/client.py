"""MCP Client — connects to external MCP servers over HTTP/SSE transport."""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from nexusai.mcp.registry import MCPRegistry, MCPServerInfo

logger = logging.getLogger(__name__)

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


class MCPClient:
    """HTTP client for communicating with a single external MCP server.

    Follows the MCP-over-HTTP transport convention:
    - ``GET /tools``                    → list available tools
    - ``POST /tools/{name}/call``       → invoke a tool (returns JSON)
    - ``GET  /tools/{name}/stream``     → stream tool output (SSE)
    """

    def __init__(self, server_url: str, registry: MCPRegistry) -> None:
        if not _HTTPX_AVAILABLE:
            raise RuntimeError(
                "httpx is required for MCPClient. Install it with: pip install httpx"
            )
        self._url = server_url.rstrip("/")
        self._registry = registry
        self._client: httpx.AsyncClient | None = None

    # ── Lifecycle ───────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open the HTTP session and fetch the server's tool list.

        Registers the server in the registry on success; marks it
        unhealthy on failure without raising.
        """
        self._client = httpx.AsyncClient(timeout=30.0)
        try:
            tools = await self.list_tools()
            existing = self._registry.get_server(self._url)
            if existing is not None:
                existing.tools = tools
                existing.healthy = True
            else:
                self._registry.register_server(MCPServerInfo(
                    url=self._url,
                    name=self._url,
                    tools=tools,
                    healthy=True,
                ))
            logger.info("Connected to MCP server %s, found %d tools", self._url, len(tools))
        except Exception as exc:
            logger.error("Failed to connect to MCP server %s: %s", self._url, exc)
            server = self._registry.get_server(self._url)
            if server:
                server.healthy = False

    async def disconnect(self) -> None:
        """Close the underlying HTTP session."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("Disconnected from MCP server %s", self._url)

    # ── Tool discovery ──────────────────────────────────────────────

    async def list_tools(self) -> list[dict]:
        """Fetch tool definitions from the server's ``/tools`` endpoint."""
        client = self._ensure_client()
        resp = await client.get(f"{self._url}/tools")
        resp.raise_for_status()
        data = resp.json()
        # Accept either {"tools": [...]} or a bare list
        if isinstance(data, list):
            return data
        return data.get("tools", [])

    # ── Tool invocation ─────────────────────────────────────────────

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict:
        """Invoke a tool and return the full JSON response.

        Returns a dict with at least ``{"result": ..., "error": null}``
        or ``{"result": null, "error": "message"}`` on failure.
        """
        client = self._ensure_client()
        try:
            resp = await client.post(
                f"{self._url}/tools/{tool_name}/call",
                json={"arguments": arguments},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("MCP tool call %s failed: HTTP %s", tool_name, exc.response.status_code)
            return {"result": None, "error": str(exc)}
        except Exception as exc:
            logger.error("MCP tool call %s error: %s", tool_name, exc)
            return {"result": None, "error": str(exc)}

    async def stream_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> AsyncGenerator[dict, None]:
        """Stream tool output via SSE.

        Yields parsed event dicts; each SSE ``data:`` line is expected to
        be JSON. Stops on a final ``{"done": true}`` event or connection
        close.
        """
        client = self._ensure_client()
        url = f"{self._url}/tools/{tool_name}/stream"
        try:
            async with client.stream(
                "GET",
                url,
                params={"arguments": str(arguments)},
                timeout=None,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    import json  # noqa: PLC0415
                    try:
                        event = json.loads(payload)
                        yield event
                        if event.get("done"):
                            break
                    except Exception:
                        logger.debug("Could not parse SSE payload: %r", payload)
        except Exception as exc:
            logger.error("MCP stream_tool %s error: %s", tool_name, exc)
            yield {"result": None, "error": str(exc), "done": True}

    # ── Helpers ─────────────────────────────────────────────────────

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "MCPClient is not connected. Call await client.connect() first."
            )
        return self._client
