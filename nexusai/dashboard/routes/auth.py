"""Dashboard authentication endpoints — login, logout, and current-user."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from nexusai.dashboard.auth import JWTBearer, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request / Response Models ────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    username: str
    role: str


# ── Helpers ──────────────────────────────────────────────────────


def _get_bearer(nexus_app: Any) -> JWTBearer:
    """Build a JWTBearer instance from nexus_app config."""
    secret: str = (
        nexus_app.config.get("dashboard.jwt_secret", "change-me-in-local-yaml")
        if nexus_app is not None
        else "change-me-in-local-yaml"
    )
    return JWTBearer(secret=secret)


# ── Endpoint Factories ────────────────────────────────────────────
# Endpoints are registered via create_auth_router() so the nexus_app
# reference is available in closures without global state.


def create_auth_router(nexus_app: Any = None) -> APIRouter:
    """Return an APIRouter with auth endpoints wired to *nexus_app*."""

    _router = APIRouter(prefix="/api/auth", tags=["auth"])

    def _config_get(key: str, default: Any = None) -> Any:
        if nexus_app is not None and hasattr(nexus_app, "config"):
            return nexus_app.config.get(key, default)
        return default

    jwt_secret: str = _config_get("dashboard.jwt_secret", "change-me-in-local-yaml")
    token_expires: int = int(_config_get("dashboard.token_expires_minutes", 60))
    bearer = JWTBearer(secret=jwt_secret)

    @_router.post("/login", response_model=TokenResponse)
    async def login(body: LoginRequest) -> TokenResponse:
        """Validate credentials and return a JWT access token."""
        admin_username: str = _config_get("dashboard.admin_username", "admin")
        admin_password: str = _config_get("dashboard.admin_password", "admin")

        if body.username != admin_username or body.password != admin_password:
            logger.warning("Failed login attempt for user '%s'", body.username)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = create_access_token(
            data={"sub": body.username, "role": "admin"},
            secret=jwt_secret,
            expires_minutes=token_expires,
        )
        logger.info("User '%s' logged in successfully", body.username)
        return TokenResponse(access_token=token)

    @_router.post("/logout")
    async def logout() -> dict[str, str]:
        """Logout endpoint — token invalidation is handled client-side."""
        return {"detail": "Logged out. Discard your token client-side."}

    @_router.get("/me", response_model=UserInfo)
    async def me(claims: dict[str, Any] = Depends(bearer)) -> UserInfo:
        """Return information about the currently authenticated user."""
        return UserInfo(
            username=claims.get("sub", "unknown"),
            role=claims.get("role", "user"),
        )

    return _router
