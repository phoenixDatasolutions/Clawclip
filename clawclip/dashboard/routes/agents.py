"""Dashboard agent management endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from clawclip.dashboard.auth import JWTBearer

logger = logging.getLogger(__name__)


# ── Response Models ───────────────────────────────────────────────


class AgentSummary(BaseModel):
    agent_id: str
    agent_type: str
    status: str
    user_id: str
    total_cost_usd: float
    total_tokens: int
    conversation_id: str | None = None
    parent_agent_id: str | None = None


class AgentRunSummary(BaseModel):
    run_id: str
    agent_instance_id: str
    task_description: str
    status: str
    cost_usd: float
    duration_ms: int
    started_at: str
    completed_at: str | None = None
    error_message: str | None = None


# ── Router Factory ────────────────────────────────────────────────


def create_agents_router(nexus_app: Any = None) -> APIRouter:
    """Return an APIRouter with agent management endpoints."""

    _router = APIRouter(prefix="/api/agents", tags=["agents"])

    def _config_get(key: str, default: Any = None) -> Any:
        if nexus_app is not None and hasattr(nexus_app, "config"):
            return nexus_app.config.get(key, default)
        return default

    jwt_secret: str = _config_get("dashboard.jwt_secret", "change-me-in-local-yaml")
    bearer = JWTBearer(secret=jwt_secret)

    @_router.get("", response_model=list[AgentSummary])
    async def list_agents(
        _claims: dict[str, Any] = Depends(bearer),
    ) -> list[AgentSummary]:
        """List all agent instances with their current status."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return []
        try:
            from sqlalchemy import select
            from clawclip.storage.models.agent import AgentInstance

            async with nexus_app.db.session() as session:
                rows = (await session.execute(select(AgentInstance))).scalars().all()
            return [
                AgentSummary(
                    agent_id=r.id,
                    agent_type=r.agent_type,
                    status=r.status,
                    user_id=r.user_id,
                    total_cost_usd=r.total_cost_usd,
                    total_tokens=r.total_tokens,
                    conversation_id=r.conversation_id,
                    parent_agent_id=r.parent_agent_id,
                )
                for r in rows
            ]
        except Exception as exc:
            logger.exception("Failed to list agents")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.post("/{agent_id}/pause")
    async def pause_agent(
        agent_id: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, str]:
        """Pause a running agent by updating its status in the database."""
        return await _set_agent_status(nexus_app, agent_id, "paused")

    @_router.post("/{agent_id}/resume")
    async def resume_agent(
        agent_id: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, str]:
        """Resume a paused agent."""
        return await _set_agent_status(nexus_app, agent_id, "idle")

    @_router.delete("/{agent_id}")
    async def cancel_agent(
        agent_id: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, str]:
        """Cancel and mark an agent as cancelled."""
        return await _set_agent_status(nexus_app, agent_id, "cancelled")

    @_router.get("/{agent_id}/runs", response_model=list[AgentRunSummary])
    async def list_agent_runs(
        agent_id: str,
        limit: int = 50,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> list[AgentRunSummary]:
        """List recent runs for a specific agent instance."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return []
        try:
            from sqlalchemy import select
            from clawclip.storage.models.agent import AgentRun

            async with nexus_app.db.session() as session:
                stmt = (
                    select(AgentRun)
                    .where(AgentRun.agent_instance_id == agent_id)
                    .order_by(AgentRun.started_at.desc())
                    .limit(limit)
                )
                rows = (await session.execute(stmt)).scalars().all()
            return [_run_to_summary(r) for r in rows]
        except Exception as exc:
            logger.exception("Failed to list runs for agent %s", agent_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.get("/runs/{run_id}", response_model=AgentRunSummary)
    async def get_run(
        run_id: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> AgentRunSummary:
        """Get details for a specific agent run."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available",
            )
        try:
            from sqlalchemy import select
            from clawclip.storage.models.agent import AgentRun

            async with nexus_app.db.session() as session:
                row = (
                    await session.execute(select(AgentRun).where(AgentRun.id == run_id))
                ).scalar_one_or_none()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run '{run_id}' not found",
                )
            return _run_to_summary(row)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to get run %s", run_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    return _router


# ── Shared Helpers ────────────────────────────────────────────────


async def _set_agent_status(
    nexus_app: Any,
    agent_id: str,
    new_status: str,
) -> dict[str, str]:
    """Update an AgentInstance status row."""
    if nexus_app is None or not hasattr(nexus_app, "db"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )
    try:
        from sqlalchemy import select
        from clawclip.storage.models.agent import AgentInstance

        async with nexus_app.db.session() as session:
            instance = (
                await session.execute(
                    select(AgentInstance).where(AgentInstance.id == agent_id)
                )
            ).scalar_one_or_none()
            if instance is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent '{agent_id}' not found",
                )
            instance.status = new_status
            await session.flush()
        return {"detail": f"Agent '{agent_id}' set to '{new_status}'"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to set agent %s status to %s", agent_id, new_status)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


def _run_to_summary(run: Any) -> AgentRunSummary:
    return AgentRunSummary(
        run_id=run.id,
        agent_instance_id=run.agent_instance_id,
        task_description=run.task_description or "",
        status=run.status,
        cost_usd=run.cost_usd,
        duration_ms=run.duration_ms,
        started_at=run.started_at.isoformat() if run.started_at else "",
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        error_message=run.error_message,
    )
