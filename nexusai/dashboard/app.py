"""Dashboard FastAPI application factory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from nexusai.dashboard.routes.agents import create_agents_router
from nexusai.dashboard.routes.analytics import create_analytics_router
from nexusai.dashboard.routes.auth import create_auth_router
from nexusai.dashboard.routes.conversations import create_conversations_router
from nexusai.dashboard.routes.settings import create_settings_router
from nexusai.dashboard.routes.skills import create_skills_router
from nexusai.dashboard.routes.system import create_system_router
from nexusai.dashboard.routes.users import create_users_router

logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).parent / "frontend"


def create_dashboard_app(nexus_app: Any = None) -> FastAPI:
    """Create and configure the NexusAI Dashboard FastAPI application.

    Args:
        nexus_app: The running NexusAI application instance (provides access
            to config, db, event_bus, skill_manager, agent_engine, etc.).
            Pass ``None`` when running the dashboard standalone for testing.

    Returns:
        A fully configured FastAPI application ready to be served or mounted.
    """
    app = FastAPI(
        title="NexusAI Dashboard",
        version="1.0.0",
        description="Web dashboard for managing and monitoring the NexusAI platform.",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ── CORS ──────────────────────────────────────────────────────
    allowed_origins: list[str] = ["*"]
    if nexus_app is not None and hasattr(nexus_app, "config"):
        configured = nexus_app.config.get("dashboard.cors_origins")
        if isinstance(configured, list) and configured:
            allowed_origins = configured

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── REST Routers ──────────────────────────────────────────────
    app.include_router(create_auth_router(nexus_app))
    app.include_router(create_settings_router(nexus_app))
    app.include_router(create_agents_router(nexus_app))
    app.include_router(create_conversations_router(nexus_app))
    app.include_router(create_analytics_router(nexus_app))
    app.include_router(create_skills_router(nexus_app))
    app.include_router(create_users_router(nexus_app))
    app.include_router(create_system_router(nexus_app))

    # ── WebSocket Endpoints ───────────────────────────────────────
    @app.websocket("/ws/agents")
    async def ws_agents(websocket: WebSocket) -> None:
        """Live agent activity stream."""
        from nexusai.dashboard.ws.live_agents import websocket_agents

        event_bus = _resolve(nexus_app, "event_bus")
        if event_bus is None:
            await websocket.close(code=1011, reason="EventBus not available")
            return
        await websocket_agents(websocket, event_bus)

    @app.websocket("/ws/logs")
    async def ws_logs(websocket: WebSocket) -> None:
        """Live log line stream."""
        from nexusai.dashboard.ws.live_logs import websocket_logs

        await websocket_logs(websocket)

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket) -> None:
        """Interactive chat with an agent."""
        from nexusai.dashboard.ws.live_chat import websocket_chat

        agent_engine = _resolve(nexus_app, "agent_engine")
        event_bus = _resolve(nexus_app, "event_bus")
        await websocket_chat(websocket, agent_engine=agent_engine, event_bus=event_bus)

    # ── Static Files / SPA ────────────────────────────────────────
    _mount_frontend(app)

    logger.info("NexusAI Dashboard application created")
    return app


def _resolve(nexus_app: Any, attr: str) -> Any:
    """Safely resolve an attribute from nexus_app."""
    if nexus_app is None:
        return None
    return getattr(nexus_app, attr, None)


def _mount_frontend(app: FastAPI) -> None:
    """Mount the built frontend static files, or serve the fallback index.html."""
    dist_dir = _FRONTEND_DIR / "dist"
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
        logger.info("Serving built frontend from %s", dist_dir)
        return

    # Fallback: serve the raw frontend directory (index.html placeholder)
    if _FRONTEND_DIR.exists() and (_FRONTEND_DIR / "index.html").exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(_FRONTEND_DIR)),
            name="frontend_static",
        )

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def serve_index() -> HTMLResponse:
            content = (_FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
            return HTMLResponse(content=content)

        logger.info("Serving placeholder frontend from %s", _FRONTEND_DIR)
    else:
        logger.warning(
            "No frontend found at %s — only the REST API and WebSocket endpoints are active.",
            _FRONTEND_DIR,
        )
