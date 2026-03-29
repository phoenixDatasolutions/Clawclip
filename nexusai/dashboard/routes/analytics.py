"""Dashboard analytics endpoints — cost summaries, usage metrics, and time-series data."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from nexusai.dashboard.auth import JWTBearer

logger = logging.getLogger(__name__)


# ── Response Models ───────────────────────────────────────────────


class CostSummary(BaseModel):
    today_usd: float
    week_usd: float
    month_usd: float
    by_model: dict[str, float]
    by_agent: dict[str, float]


class UsageSummary(BaseModel):
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_duration_ms: float
    total_input_tokens: int
    total_output_tokens: int


class ModelUsage(BaseModel):
    model: str
    provider: str
    request_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class TimelineBucket(BaseModel):
    bucket: str  # ISO datetime string for the bucket start
    request_count: int
    cost_usd: float
    input_tokens: int
    output_tokens: int


# ── Router Factory ────────────────────────────────────────────────


def create_analytics_router(nexus_app: Any = None) -> APIRouter:
    """Return an APIRouter with analytics endpoints."""

    _router = APIRouter(prefix="/api/analytics", tags=["analytics"])

    def _config_get(key: str, default: Any = None) -> Any:
        if nexus_app is not None and hasattr(nexus_app, "config"):
            return nexus_app.config.get(key, default)
        return default

    jwt_secret: str = _config_get("dashboard.jwt_secret", "change-me-in-local-yaml")
    bearer = JWTBearer(secret=jwt_secret)

    @_router.get("/costs", response_model=CostSummary)
    async def get_costs(
        _claims: dict[str, Any] = Depends(bearer),
    ) -> CostSummary:
        """Return cost summaries: today, week, month, grouped by model and agent."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return CostSummary(today_usd=0, week_usd=0, month_usd=0, by_model={}, by_agent={})
        try:
            from sqlalchemy import func, select
            from nexusai.storage.models.cost import CostEntry

            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = now - timedelta(days=7)
            month_start = now - timedelta(days=30)

            async with nexus_app.db.session() as session:
                # Period aggregations
                today_usd = await _sum_cost(session, CostEntry, today_start)
                week_usd = await _sum_cost(session, CostEntry, week_start)
                month_usd = await _sum_cost(session, CostEntry, month_start)

                # By model
                model_rows = (
                    await session.execute(
                        select(CostEntry.model, func.sum(CostEntry.cost_usd))
                        .where(CostEntry.created_at >= month_start)
                        .group_by(CostEntry.model)
                    )
                ).all()
                by_model = {r[0]: float(r[1] or 0) for r in model_rows}

                # By agent
                agent_rows = (
                    await session.execute(
                        select(CostEntry.agent_id, func.sum(CostEntry.cost_usd))
                        .where(
                            CostEntry.created_at >= month_start,
                            CostEntry.agent_id.isnot(None),
                        )
                        .group_by(CostEntry.agent_id)
                    )
                ).all()
                by_agent = {r[0]: float(r[1] or 0) for r in agent_rows if r[0]}

            return CostSummary(
                today_usd=today_usd,
                week_usd=week_usd,
                month_usd=month_usd,
                by_model=by_model,
                by_agent=by_agent,
            )
        except Exception as exc:
            logger.exception("Failed to get cost analytics")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.get("/usage", response_model=UsageSummary)
    async def get_usage(
        days: int = Query(7, ge=1, le=90),
        _claims: dict[str, Any] = Depends(bearer),
    ) -> UsageSummary:
        """Return aggregate usage metrics for the last *days* days."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return UsageSummary(
                total_requests=0,
                successful_requests=0,
                failed_requests=0,
                avg_duration_ms=0.0,
                total_input_tokens=0,
                total_output_tokens=0,
            )
        try:
            from sqlalchemy import func, select
            from nexusai.storage.models.agent import AgentRun

            since = datetime.now(timezone.utc) - timedelta(days=days)
            async with nexus_app.db.session() as session:
                rows = (
                    await session.execute(
                        select(
                            func.count(AgentRun.id),
                            func.sum(
                                AgentRun.input_tokens
                            ),
                            func.sum(AgentRun.output_tokens),
                            func.avg(AgentRun.duration_ms),
                        ).where(AgentRun.started_at >= since)
                    )
                ).one()
                total = int(rows[0] or 0)
                input_tokens = int(rows[1] or 0)
                output_tokens = int(rows[2] or 0)
                avg_duration = float(rows[3] or 0)

                failed = (
                    await session.execute(
                        select(func.count(AgentRun.id)).where(
                            AgentRun.started_at >= since,
                            AgentRun.status == "failed",
                        )
                    )
                ).scalar_one()

            return UsageSummary(
                total_requests=total,
                successful_requests=total - int(failed),
                failed_requests=int(failed),
                avg_duration_ms=avg_duration,
                total_input_tokens=input_tokens,
                total_output_tokens=output_tokens,
            )
        except Exception as exc:
            logger.exception("Failed to get usage analytics")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.get("/models", response_model=list[ModelUsage])
    async def get_model_usage(
        days: int = Query(30, ge=1, le=365),
        _claims: dict[str, Any] = Depends(bearer),
    ) -> list[ModelUsage]:
        """Return per-model usage breakdown for the last *days* days."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return []
        try:
            from sqlalchemy import func, select
            from nexusai.storage.models.cost import CostEntry

            since = datetime.now(timezone.utc) - timedelta(days=days)
            async with nexus_app.db.session() as session:
                rows = (
                    await session.execute(
                        select(
                            CostEntry.model,
                            CostEntry.provider,
                            func.count(CostEntry.id),
                            func.sum(CostEntry.input_tokens),
                            func.sum(CostEntry.output_tokens),
                            func.sum(CostEntry.cost_usd),
                        )
                        .where(CostEntry.created_at >= since)
                        .group_by(CostEntry.model, CostEntry.provider)
                        .order_by(func.sum(CostEntry.cost_usd).desc())
                    )
                ).all()
            return [
                ModelUsage(
                    model=r[0],
                    provider=r[1],
                    request_count=int(r[2] or 0),
                    input_tokens=int(r[3] or 0),
                    output_tokens=int(r[4] or 0),
                    cost_usd=float(r[5] or 0),
                )
                for r in rows
            ]
        except Exception as exc:
            logger.exception("Failed to get model usage analytics")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.get("/timeline", response_model=list[TimelineBucket])
    async def get_timeline(
        days: int = Query(7, ge=1, le=90),
        bucket: str = Query("hourly", pattern="^(hourly|daily)$"),
        _claims: dict[str, Any] = Depends(bearer),
    ) -> list[TimelineBucket]:
        """Return time-series data bucketed hourly or daily for charts."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return []
        try:
            from sqlalchemy import func, select
            from nexusai.storage.models.cost import CostEntry

            since = datetime.now(timezone.utc) - timedelta(days=days)
            async with nexus_app.db.session() as session:
                rows = (
                    await session.execute(
                        select(
                            CostEntry.created_at,
                            CostEntry.cost_usd,
                            CostEntry.input_tokens,
                            CostEntry.output_tokens,
                        ).where(CostEntry.created_at >= since)
                        .order_by(CostEntry.created_at)
                    )
                ).all()

            buckets: dict[str, dict[str, Any]] = {}
            for row in rows:
                ts: datetime = row[0]
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if bucket == "hourly":
                    key = ts.replace(minute=0, second=0, microsecond=0).isoformat()
                else:
                    key = ts.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

                entry = buckets.setdefault(
                    key,
                    {"bucket": key, "request_count": 0, "cost_usd": 0.0,
                     "input_tokens": 0, "output_tokens": 0},
                )
                entry["request_count"] += 1
                entry["cost_usd"] += float(row[1] or 0)
                entry["input_tokens"] += int(row[2] or 0)
                entry["output_tokens"] += int(row[3] or 0)

            return [TimelineBucket(**v) for v in sorted(buckets.values(), key=lambda x: x["bucket"])]
        except Exception as exc:
            logger.exception("Failed to get timeline analytics")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    return _router


# ── Shared helpers ────────────────────────────────────────────────


async def _sum_cost(session: Any, model: Any, since: datetime) -> float:
    from sqlalchemy import func, select

    result = await session.execute(
        select(func.sum(model.cost_usd)).where(model.created_at >= since)
    )
    return float(result.scalar_one() or 0)
