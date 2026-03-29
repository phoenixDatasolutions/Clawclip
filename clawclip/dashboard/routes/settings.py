"""Dashboard settings endpoints — config management and credential listing."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from clawclip.dashboard.auth import JWTBearer

logger = logging.getLogger(__name__)


# ── Request / Response Models ────────────────────────────────────


class SettingsUpdate(BaseModel):
    data: dict[str, Any]


class FeatureToggles(BaseModel):
    features: dict[str, bool]


class CredentialCreate(BaseModel):
    owner_type: str
    owner_id: str
    key_name: str
    value: str


# ── Router Factory ────────────────────────────────────────────────


def create_settings_router(nexus_app: Any = None) -> APIRouter:
    """Return an APIRouter with settings endpoints wired to *nexus_app*."""

    _router = APIRouter(prefix="/api/settings", tags=["settings"])

    def _config_get(key: str, default: Any = None) -> Any:
        if nexus_app is not None and hasattr(nexus_app, "config"):
            return nexus_app.config.get(key, default)
        return default

    jwt_secret: str = _config_get("dashboard.jwt_secret", "change-me-in-local-yaml")
    bearer = JWTBearer(secret=jwt_secret)

    @_router.get("")
    async def get_settings(
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, Any]:
        """Return the current merged config (default.yaml + local.yaml)."""
        if nexus_app is None or not hasattr(nexus_app, "config"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Config not available",
            )
        # Return a copy; never expose raw secrets
        data: dict[str, Any] = nexus_app.config.data.copy()
        # Scrub obvious secret fields
        for sensitive_key in ("jwt_secret", "admin_password", "bot_token", "api_key"):
            _scrub_key(data, sensitive_key)
        return data

    @_router.put("")
    async def update_settings(
        body: SettingsUpdate,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, str]:
        """Persist overrides to local.yaml and trigger a hot-reload."""
        if nexus_app is None or not hasattr(nexus_app, "config"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Config not available",
            )
        try:
            nexus_app.config.save_local(body.data)
            nexus_app.config.reload()
        except Exception as exc:
            logger.exception("Failed to update settings")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        return {"detail": "Settings saved and reloaded"}

    @_router.get("/features")
    async def get_features(
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, Any]:
        """Return the features section of the config as a flat enabled/disabled map."""
        features_raw: Any = _config_get("features", {})
        if not isinstance(features_raw, dict):
            return {}
        return {
            name: bool(value.get("enabled", False)) if isinstance(value, dict) else bool(value)
            for name, value in features_raw.items()
        }

    @_router.put("/features")
    async def update_features(
        body: FeatureToggles,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, str]:
        """Toggle features on or off and persist to local.yaml."""
        if nexus_app is None or not hasattr(nexus_app, "config"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Config not available",
            )
        for feature, enabled in body.features.items():
            nexus_app.config.set(f"features.{feature}.enabled", enabled)
        try:
            nexus_app.config.save_local()
        except Exception as exc:
            logger.exception("Failed to save feature toggles")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        return {"detail": f"Updated {len(body.features)} feature(s)"}

    @_router.get("/credentials")
    async def list_credentials(
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, Any]:
        """List stored credential names (never values) from the database."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return {"credentials": []}
        try:
            from sqlalchemy import select
            from clawclip.storage.models.credential import EncryptedCredential

            async with nexus_app.db.session() as session:
                rows = await session.execute(
                    select(
                        EncryptedCredential.owner_type,
                        EncryptedCredential.owner_id,
                        EncryptedCredential.key_name,
                    )
                )
                credentials = [
                    {"owner_type": r.owner_type, "owner_id": r.owner_id, "key_name": r.key_name}
                    for r in rows
                ]
            return {"credentials": credentials}
        except Exception as exc:
            logger.exception("Failed to list credentials")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.post("/credentials", status_code=status.HTTP_201_CREATED)
    async def create_credential(
        body: CredentialCreate,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, str]:
        """Store a new credential via the vault (encrypted at rest)."""
        if nexus_app is None or not hasattr(nexus_app, "vault"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Vault not available",
            )
        try:
            await nexus_app.vault.store(
                owner_type=body.owner_type,
                owner_id=body.owner_id,
                key_name=body.key_name,
                value=body.value,
            )
        except Exception as exc:
            logger.exception("Failed to store credential")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        return {"detail": f"Credential '{body.key_name}' stored"}

    return _router


def _scrub_key(data: dict[str, Any], sensitive: str) -> None:
    """Recursively redact values whose key contains *sensitive*."""
    for key in list(data.keys()):
        if sensitive.lower() in key.lower():
            data[key] = "***"
        elif isinstance(data[key], dict):
            _scrub_key(data[key], sensitive)
