"""Unit tests for nexusai.mcp.registry — MCPRegistry."""

from __future__ import annotations

import pytest

from nexusai.mcp.registry import MCPRegistry, MCPServerInfo


def _server(url: str, name: str, healthy: bool = True, tools: list | None = None) -> MCPServerInfo:
    return MCPServerInfo(
        url=url,
        name=name,
        description=f"{name} server",
        tools=tools or [],
        healthy=healthy,
    )


@pytest.mark.unit
class TestMCPRegistry:

    def test_register_server(self) -> None:
        """Registered server appears in list_servers()."""
        registry = MCPRegistry()
        server = _server("http://localhost:8000", "my-server")
        registry.register_server(server)

        servers = registry.list_servers()
        assert len(servers) == 1
        assert servers[0].name == "my-server"

    def test_unregister_server(self) -> None:
        """Unregistering a server removes it from list_servers()."""
        registry = MCPRegistry()
        server = _server("http://localhost:8001", "temp-server")
        registry.register_server(server)
        registry.unregister_server("http://localhost:8001")

        assert registry.list_servers() == []

    def test_get_all_tools_healthy_only(self) -> None:
        """get_all_tools() excludes tools from unhealthy servers."""
        registry = MCPRegistry()
        registry.register_server(_server(
            "http://ok:8000", "ok", healthy=True,
            tools=[{"name": "tool_a", "description": ""}],
        ))
        registry.register_server(_server(
            "http://bad:8000", "bad", healthy=False,
            tools=[{"name": "tool_b", "description": ""}],
        ))

        tools = registry.get_all_tools()
        names = [t["name"] for t in tools]
        assert "tool_a" in names
        assert "tool_b" not in names

    def test_get_server_by_url(self) -> None:
        """get_server(url) returns the correct MCPServerInfo."""
        registry = MCPRegistry()
        server = _server("http://find-me:9000", "find-me")
        registry.register_server(server)

        found = registry.get_server("http://find-me:9000")
        assert found is not None
        assert found.name == "find-me"
