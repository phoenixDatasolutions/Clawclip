"""MCP Bridge — adapts external MCP servers into NexusAI Skill objects."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nexusai.core.types import SkillContext, SkillResult, ToolDefinition
from nexusai.mcp.client import MCPClient
from nexusai.mcp.registry import MCPServerInfo

logger = logging.getLogger(__name__)


def _mcp_tool_to_definition(raw: dict) -> ToolDefinition:
    """Convert a raw MCP tool descriptor to a NexusAI ToolDefinition."""
    return ToolDefinition(
        name=raw.get("name", "unknown"),
        description=raw.get("description", ""),
        parameters=raw.get("inputSchema", raw.get("parameters", {"type": "object", "properties": {}})),
    )


class MCPSkillAdapter:
    """Implements the NexusAI Skill protocol, wrapping an entire MCP server.

    All tools from the remote MCP server are surfaced as a single skill
    whose ``name`` is ``mcp_{server_name}``.  Execution delegates each
    ``tool_name`` call to :meth:`MCPClient.call_tool`.
    """

    def __init__(self, server_info: MCPServerInfo, client: MCPClient) -> None:
        self._server_info = server_info
        self._client = client
        self._skill_name = f"mcp_{server_info.name.replace(' ', '_').lower()}"

    # ── Skill protocol properties ───────────────────────────────────

    @property
    def name(self) -> str:
        return self._skill_name

    @property
    def description(self) -> str:
        return self._server_info.description or f"MCP server at {self._server_info.url}"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [_mcp_tool_to_definition(t) for t in self._server_info.tools]

    @property
    def triggers(self) -> list[str]:
        return []

    @property
    def required_permissions(self) -> list[str]:
        return []

    # ── Skill protocol methods ──────────────────────────────────────

    async def initialize(self, context: SkillContext) -> None:
        """Ensure the MCP client is connected."""
        await self._client.connect()

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        """Delegate tool execution to the remote MCP server."""
        raw = await self._client.call_tool(tool_name, arguments)
        error = raw.get("error")
        if error:
            return SkillResult(success=False, output=str(error), error=str(error))
        result = raw.get("result", "")
        return SkillResult(success=True, output=str(result) if result is not None else "")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        return SkillResult(
            success=False,
            output=f"Trigger '{trigger}' not supported by MCP skill adapter",
            error="unsupported",
        )

    async def shutdown(self) -> None:
        """Disconnect from the MCP server."""
        await self._client.disconnect()


def create_skill_from_server(
    server: MCPServerInfo,
    client: MCPClient,
) -> MCPSkillAdapter:
    """Factory: create a NexusAI Skill that wraps an MCP server.

    Args:
        server: Registry metadata for the MCP server.
        client: A connected (or about-to-be-connected) :class:`MCPClient`.

    Returns:
        An :class:`MCPSkillAdapter` that satisfies the Skill protocol.
    """
    return MCPSkillAdapter(server_info=server, client=client)
