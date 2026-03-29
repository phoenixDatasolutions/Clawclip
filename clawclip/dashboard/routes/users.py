"""Dashboard user management endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from clawclip.dashboard.auth import JWTBearer
from clawclip.core.enums import Role

logger = logging.getLogger(__name__)


# ── Request / Response Models ─────────────────────────────────────


class UserDetail(BaseModel):
    user_id: str
    display_name: str | None
    role: str
    is_active: bool
    created_at: str
    platform_links: list[dict[str, Any]]


class RoleUpdate(BaseModel):
    role: str


# ── Router Factory ────────────────────────────────────────────────


def create_users_router(nexus_app: Any = None) -> APIRouter:
    """Return an APIRouter with user management endpoints."""

    _router = APIRouter(prefix="/api/users", tags=["users"])

    def _config_get(key: str, default: Any = None) -> Any:
        if nexus_app is not None and hasattr(nexus_app, "config"):
            return nexus_app.config.get(key, default)
        return default

    jwt_secret: str = _config_get("dashboard.jwt_secret", "change-me-in-local-yaml")
    bearer = JWTBearer(secret=jwt_secret)

    @_router.get("", response_model=list[UserDetail])
    async def list_users(
        _claims: dict[str, Any] = Depends(bearer),
    ) -> list[UserDetail]:
        """List all users in the system."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return []
        try:
            from sqlalchemy import select
            from clawclip.storage.models.user import User

            async with nexus_app.db.session() as session:
                rows = (await session.execute(select(User))).scalars().all()
            return [_user_to_detail(r) for r in rows]
        except Exception as exc:
            logger.exception("Failed to list users")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.get("/{user_id}", response_model=UserDetail)
    async def get_user(
        user_id: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> UserDetail:
        """Get details for a specific user."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available",
            )
        try:
            from sqlalchemy import select
            from clawclip.storage.models.user import User

            async with nexus_app.db.session() as session:
                row = (
                    await session.execute(select(User).where(User.id == user_id))
                ).scalar_one_or_none()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User '{user_id}' not found",
                )
            return _user_to_detail(row)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to get user %s", user_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.put("/{user_id}/role")
    async def update_user_role(
        user_id: str,
        body: RoleUpdate,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, str]:
        """Change a user's role."""
        # Validate the role value
        valid_roles = {r.value for r in Role}
        if body.role not in valid_roles:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid role '{body.role}'. Must be one of: {sorted(valid_roles)}",
            )
        if nexus_app is None or not hasattr(nexus_app, "db"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available",
            )
        try:
            from sqlalchemy import select
            from clawclip.storage.models.user import User

            async with nexus_app.db.session() as session:
                row = (
                    await session.execute(select(User).where(User.id == user_id))
                ).scalar_one_or_none()
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"User '{user_id}' not found",
                    )
                row.role = body.role
                await session.flush()
            return {"detail": f"User '{user_id}' role updated to '{body.role}'"}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to update role for user %s", user_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def ban_user(
        user_id: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> None:
        """Ban/deactivate a user (sets is_active=False)."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available",
            )
        try:
            from sqlalchemy import select
            from clawclip.storage.models.user import User

            async with nexus_app.db.session() as session:
                row = (
                    await session.execute(select(User).where(User.id == user_id))
                ).scalar_one_or_none()
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"User '{user_id}' not found",
                    )
                row.is_active = False
                await session.flush()
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to ban user %s", user_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    return _router


def _user_to_detail(row: Any) -> UserDetail:
    links = [
        {
            "platform": lnk.platform,
            "platform_user_id": lnk.platform_user_id,
            "platform_username": lnk.platform_username,
        }
        for lnk in getattr(row, "platform_links", [])
    ]
    return UserDetail(
        user_id=row.id,
        display_name=row.display_name,
        role=row.role,
        is_active=row.is_active,
        created_at=row.created_at.isoformat() if row.created_at else "",
        platform_links=links,
    )
