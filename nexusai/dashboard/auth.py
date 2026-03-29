"""Dashboard JWT authentication utilities and FastAPI dependencies."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"


def create_access_token(
    data: dict[str, Any],
    secret: str,
    expires_minutes: int = 60,
) -> str:
    """Create a signed JWT access token.

    Args:
        data: Claims to embed in the token payload.
        secret: HMAC signing secret.
        expires_minutes: Token lifetime in minutes (default 60).

    Returns:
        Encoded JWT string.
    """
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload["exp"] = expire
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def verify_token(token: str, secret: str) -> dict[str, Any] | None:
    """Verify a JWT token and return the decoded payload, or None if invalid.

    Args:
        token: Encoded JWT string.
        secret: HMAC signing secret.

    Returns:
        Decoded claims dict, or None on any verification failure.
    """
    try:
        payload: dict[str, Any] = jwt.decode(token, secret, algorithms=[_ALGORITHM])
        return payload
    except JWTError as exc:
        logger.debug("JWT verification failed: %s", exc)
        return None


class JWTBearer(HTTPBearer):
    """FastAPI security dependency that validates Bearer JWT tokens.

    Usage::

        @router.get("/protected")
        async def protected(claims: dict = Depends(JWTBearer(secret="…"))):
            return {"user": claims["sub"]}
    """

    def __init__(self, secret: str, auto_error: bool = True) -> None:
        super().__init__(auto_error=auto_error)
        self._secret = secret

    async def __call__(self, request: Request) -> dict[str, Any]:  # type: ignore[override]
        credentials: HTTPAuthorizationCredentials | None = await super().__call__(request)
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authenticated",
            )
        payload = verify_token(credentials.credentials, self._secret)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
