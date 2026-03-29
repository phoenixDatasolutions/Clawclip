"""Dashboard skill management endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from clawclip.dashboard.auth import JWTBearer

logger = logging.getLogger(__name__)


# ── Response Models ───────────────────────────────────────────────


class SkillSummary(BaseModel):
    name: str
    description: str
    enabled: bool
    tool_count: int
    trigger_count: int


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    required_permissions: list[str]


# ── Router Factory ────────────────────────────────────────────────


def create_skills_router(nexus_app: Any = None) -> APIRouter:
    """Return an APIRouter with skill management endpoints."""

    _router = APIRouter(prefix="/api/skills", tags=["skills"])

    def _config_get(key: str, default: Any = None) -> Any:
        if nexus_app is not None and hasattr(nexus_app, "config"):
            return nexus_app.config.get(key, default)
        return default

    jwt_secret: str = _config_get("dashboard.jwt_secret", "change-me-in-local-yaml")
    bearer = JWTBearer(secret=jwt_secret)

    def _get_skill_registry() -> Any:
        if nexus_app is None:
            return None
        if hasattr(nexus_app, "skill_registry"):
            return nexus_app.skill_registry
        if hasattr(nexus_app, "skill_manager") and hasattr(nexus_app.skill_manager, "_registry"):
            return nexus_app.skill_manager._registry
        return None

    @_router.get("", response_model=list[SkillSummary])
    async def list_skills(
        _claims: dict[str, Any] = Depends(bearer),
    ) -> list[SkillSummary]:
        """List all registered skills with their enabled status."""
        registry = _get_skill_registry()
        if registry is None:
            return []
        try:
            results: list[SkillSummary] = []
            for name, skill in registry:
                enabled = _config_get(f"features.{name}.enabled", True)
                results.append(
                    SkillSummary(
                        name=name,
                        description=getattr(skill, "description", ""),
                        enabled=bool(enabled),
                        tool_count=len(getattr(skill, "tools", [])),
                        trigger_count=len(getattr(skill, "triggers", [])),
                    )
                )
            return results
        except Exception as exc:
            logger.exception("Failed to list skills")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.post("/{skill_name}/enable")
    async def enable_skill(
        skill_name: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, str]:
        """Enable a skill by setting its feature flag."""
        return await _set_skill_enabled(nexus_app, skill_name, enabled=True)

    @_router.post("/{skill_name}/disable")
    async def disable_skill(
        skill_name: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, str]:
        """Disable a skill by clearing its feature flag."""
        return await _set_skill_enabled(nexus_app, skill_name, enabled=False)

    @_router.get("/{skill_name}/tools", response_model=list[ToolInfo])
    async def list_skill_tools(
        skill_name: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> list[ToolInfo]:
        """List all tools exposed by a specific skill."""
        registry = _get_skill_registry()
        if registry is None:
            return []
        try:
            skill = registry.get(skill_name)
            if skill is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill '{skill_name}' not found",
                )
            return [
                ToolInfo(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                    required_permissions=tool.required_permissions,
                )
                for tool in getattr(skill, "tools", [])
            ]
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to list tools for skill %s", skill_name)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    return _router


async def _set_skill_enabled(nexus_app: Any, skill_name: str, *, enabled: bool) -> dict[str, str]:
    if nexus_app is None or not hasattr(nexus_app, "config"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Config not available",
        )
    try:
        nexus_app.config.set(f"features.{skill_name}.enabled", enabled)
        nexus_app.config.save_local()
    except Exception as exc:
        logger.exception("Failed to toggle skill %s", skill_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    state = "enabled" if enabled else "disabled"
    return {"detail": f"Skill '{skill_name}' {state}"}
