"""Dashboard system health and diagnostic endpoints."""

from __future__ import annotations

import logging
import platform
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from clawclip.dashboard.auth import JWTBearer

logger = logging.getLogger(__name__)

# Record start time for uptime calculation
_START_TIME = time.monotonic()
_START_WALL = datetime.now(timezone.utc)


# ── Response Models ───────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    started_at: str
    cpu_percent: float | None = None
    ram_percent: float | None = None
    ram_used_mb: float | None = None
    ram_total_mb: float | None = None
    disk_percent: float | None = None
    disk_used_gb: float | None = None
    disk_total_gb: float | None = None


class VersionResponse(BaseModel):
    app_name: str
    version: str
    python_version: str
    platform: str
    environment: str


# ── Router Factory ────────────────────────────────────────────────


def create_system_router(nexus_app: Any = None) -> APIRouter:
    """Return an APIRouter with system health endpoints."""

    _router = APIRouter(prefix="/api/system", tags=["system"])

    def _config_get(key: str, default: Any = None) -> Any:
        if nexus_app is not None and hasattr(nexus_app, "config"):
            return nexus_app.config.get(key, default)
        return default

    jwt_secret: str = _config_get("dashboard.jwt_secret", "change-me-in-local-yaml")
    bearer = JWTBearer(secret=jwt_secret)

    @_router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Return system health metrics. No auth required for basic liveness checks."""
        uptime = time.monotonic() - _START_TIME
        response = HealthResponse(
            status="ok",
            uptime_seconds=round(uptime, 1),
            started_at=_START_WALL.isoformat(),
        )
        try:
            import psutil  # type: ignore[import-untyped]

            response.cpu_percent = psutil.cpu_percent(interval=0.1)
            vm = psutil.virtual_memory()
            response.ram_percent = vm.percent
            response.ram_used_mb = round(vm.used / 1024 / 1024, 1)
            response.ram_total_mb = round(vm.total / 1024 / 1024, 1)
            disk = psutil.disk_usage("/")
            response.disk_percent = disk.percent
            response.disk_used_gb = round(disk.used / 1024 / 1024 / 1024, 2)
            response.disk_total_gb = round(disk.total / 1024 / 1024 / 1024, 2)
        except ImportError:
            logger.debug("psutil not installed — skipping resource metrics")
        except Exception:
            logger.debug("Failed to collect system metrics", exc_info=True)
        return response

    @_router.get("/version", response_model=VersionResponse)
    async def version(
        _claims: dict[str, Any] = Depends(bearer),
    ) -> VersionResponse:
        """Return application version and runtime info."""
        import sys

        app_version = _config_get("version", "0.0.0")
        env = _config_get("environment", "production")
        return VersionResponse(
            app_name="ClawClip",
            version=str(app_version),
            python_version=sys.version,
            platform=platform.platform(),
            environment=str(env),
        )

    @_router.get("/logs")
    async def get_logs(
        n: int = Query(100, ge=1, le=2000, description="Number of recent log lines to return"),
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, Any]:
        """Return the last *n* log lines from the in-memory buffer or log file."""
        # Try the dashboard's in-memory LogBuffer first
        try:
            from clawclip.dashboard.ws.live_logs import _log_buffer

            lines = _log_buffer.get_recent(n)
            return {"source": "memory_buffer", "lines": lines, "count": len(lines)}
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("Could not read log buffer: %s", exc)

        # Fall back to the configured log file
        log_file: str | None = _config_get("logging.file")
        if log_file:
            try:
                from pathlib import Path

                path = Path(log_file)
                if path.exists():
                    all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                    lines = all_lines[-n:]
                    return {"source": log_file, "lines": lines, "count": len(lines)}
            except Exception as exc:
                logger.debug("Could not read log file %s: %s", log_file, exc)

        return {"source": "none", "lines": [], "count": 0}

    return _router
