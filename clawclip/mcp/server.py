"""MCP Server — exposes ClawClip skills as MCP tools over HTTP."""

from __future__ import annotations

import logging
from typing import Any

from clawclip.core.types import SkillContext, ToolDefinition
from clawclip.skills.manager import SkillManager

logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    import uvicorn
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


class MCPServer:
    """FastAPI-based HTTP server that exposes ClawClip skills as MCP tools.

    Endpoints
    ---------
    GET  /tools                      List all skill tools in MCP format.
    POST /tools/{tool_name}/call     Execute a skill tool.
    GET  /health                     Health probe.
    """

    def __init__(
        self,
        skill_manager: SkillManager,
        host: str = "0.0.0.0",
        port: int = 8090,
    ) -> None:
        if not _FASTAPI_AVAILABLE:
            raise RuntimeError(
                "fastapi and uvicorn are required for MCPServer. "
                "Install them with: pip install fastapi uvicorn"
            )
        self._skill_manager = skill_manager
        self._host = host
        self._port = port
        self._app: FastAPI = self._build_app()
        self._server: uvicorn.Server | None = None

    # ── Public interface ────────────────────────────────────────────

    async def start(self) -> None:
        """Start the HTTP server in the background."""
        import asyncio  # noqa: PLC0415

        config = uvicorn.Config(
            self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        asyncio.create_task(self._server.serve())
        logger.info("MCPServer started on %s:%s", self._host, self._port)

    async def stop(self) -> None:
        """Gracefully shut down the HTTP server."""
        if self._server is not None:
            self._server.should_exit = True
            logger.info("MCPServer stopping")

    # ── FastAPI app construction ────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="ClawClip MCP Server", version="1.0.0")

        @app.get("/health")
        async def health() -> dict:
            return {"status": "ok"}

        @app.get("/tools")
        async def list_tools() -> dict:
            tools = self._skill_manager.get_all_tools()
            return {"tools": [self._skill_to_mcp_tool(t) for t in tools]}

        @app.post("/tools/{tool_name}/call")
        async def call_tool(tool_name: str, body: dict[str, Any] = {}) -> JSONResponse:
            arguments: dict[str, Any] = body.get("arguments", {})
            ctx = SkillContext()
            result = await self._skill_manager.execute(tool_name, arguments, ctx)
            if not result.success:
                raise HTTPException(
                    status_code=500,
                    detail={"error": result.error or result.output},
                )
            return JSONResponse({"result": result.output, "artifacts": result.artifacts})

        return app

    # ── Format helpers ──────────────────────────────────────────────

    def _skill_to_mcp_tool(self, tool_def: ToolDefinition) -> dict:
        """Convert a ClawClip ToolDefinition to an MCP tool descriptor dict."""
        return {
            "name": tool_def.name,
            "description": tool_def.description,
            "inputSchema": tool_def.parameters,
        }
