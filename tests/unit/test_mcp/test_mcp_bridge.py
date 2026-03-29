"""Unit tests for nexusai.mcp.bridge — MCPSkillAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexusai.core.types import SkillContext
from nexusai.mcp.bridge import MCPSkillAdapter, _mcp_tool_to_definition
from nexusai.mcp.registry import MCPServerInfo


def _server_info(name: str = "testserver", tools: list | None = None) -> MCPServerInfo:
    return MCPServerInfo(
        url="http://mcp-server:8000",
        name=name,
        description="Test MCP server",
        tools=tools or [
            {"name": "do_thing", "description": "Does a thing", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "list_stuff", "description": "Lists stuff", "inputSchema": {"type": "object", "properties": {}}},
        ],
    )


def _mock_client(call_tool_return: dict | None = None) -> MagicMock:
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.call_tool = AsyncMock(return_value=call_tool_return or {"result": "ok"})
    return client


@pytest.mark.unit
class TestMCPBridge:

    def test_adapter_name(self) -> None:
        """Adapter name is 'mcp_<server_name>' (lowercase, spaces → underscores)."""
        adapter = MCPSkillAdapter(_server_info("testserver"), _mock_client())
        assert adapter.name == "mcp_testserver"

    def test_adapter_tools(self) -> None:
        """tools property builds ToolDefinition objects from server's tool list."""
        adapter = MCPSkillAdapter(_server_info(), _mock_client())
        tools = adapter.tools
        assert len(tools) == 2
        tool_names = {t.name for t in tools}
        assert "do_thing" in tool_names
        assert "list_stuff" in tool_names

    async def test_execute_calls_client(self) -> None:
        """execute() delegates to client.call_tool with the correct name and args."""
        client = _mock_client({"result": "called"})
        adapter = MCPSkillAdapter(_server_info(), client)
        ctx = SkillContext(user_id="u1")

        await adapter.execute("do_thing", {"param": "value"}, ctx)

        client.call_tool.assert_called_once_with("do_thing", {"param": "value"})

    async def test_skill_result_from_response(self) -> None:
        """A {'result': 'ok'} response produces a SkillResult with success=True."""
        client = _mock_client({"result": "everything is fine"})
        adapter = MCPSkillAdapter(_server_info(), client)
        ctx = SkillContext(user_id="u1")

        result = await adapter.execute("do_thing", {}, ctx)

        assert result.success is True
        assert result.output == "everything is fine"

    async def test_skill_result_error_response(self) -> None:
        """A {'error': 'something went wrong'} response produces success=False."""
        client = _mock_client({"error": "something went wrong"})
        adapter = MCPSkillAdapter(_server_info(), client)
        ctx = SkillContext(user_id="u1")

        result = await adapter.execute("do_thing", {}, ctx)

        assert result.success is False
        assert "something went wrong" in result.output
