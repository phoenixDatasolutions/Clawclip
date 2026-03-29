"""ClawClip Webhooks — FastAPI gateway for receiving and managing webhooks."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import asdict
from typing import Any

from clawclip.webhooks.router import WebhookRoute, WebhookRouter

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, HTTPException, Request, Response
    from fastapi.responses import JSONResponse

    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment,misc]


class WebhookGateway:
    """FastAPI router factory for the ClawClip webhook gateway.

    Mount the returned router on your FastAPI application::

        app.include_router(gateway.get_fastapi_router(), prefix="/api")

    Endpoints
    ---------
    GET  /webhooks                  — list registered routes
    POST /webhooks                  — register a new route
    DELETE /webhooks/{webhook_id}   — remove a route
    POST /webhooks/{webhook_id}     — receive an inbound webhook
    """

    def __init__(
        self,
        router: WebhookRouter,
        signing_secret: str | None = None,
    ) -> None:
        self._router = router
        self._secret = signing_secret

    # ── public API ────────────────────────────────────────────────

    def get_fastapi_router(self) -> Any:
        """Return a FastAPI APIRouter with all webhook endpoints registered."""
        if not _FASTAPI_AVAILABLE:
            raise RuntimeError(
                "fastapi is not installed. Install it with: pip install fastapi"
            )

        api = APIRouter(tags=["webhooks"])

        @api.get("/webhooks", summary="List registered webhook routes")
        async def list_webhooks() -> JSONResponse:
            routes = self._router.list_routes()
            return JSONResponse([self._route_to_dict(r) for r in routes])

        @api.post("/webhooks", summary="Register a new webhook route", status_code=201)
        async def register_webhook(request: Request) -> JSONResponse:
            body = await request.json()
            route = WebhookRoute(
                path=body.get("path", ""),
                parser=body.get("parser", "generic"),
                action_type=body.get("action_type", "notification"),
                action_config=body.get("action_config", {}),
            )
            self._router.add_route(route)
            logger.info("Registered webhook route: %s -> %s", route.path, route.action_type)
            return JSONResponse(self._route_to_dict(route), status_code=201)

        @api.delete("/webhooks/{webhook_id}", summary="Remove a webhook route", status_code=204)
        async def delete_webhook(webhook_id: str) -> Response:
            self._router.remove_route(webhook_id)
            logger.info("Removed webhook route: %s", webhook_id)
            return Response(status_code=204)

        @api.post("/webhooks/{webhook_id}", summary="Receive an inbound webhook")
        async def receive_webhook(webhook_id: str, request: Request) -> JSONResponse:
            raw_body = await request.body()

            # Validate HMAC signature if a secret is configured.
            if self._secret:
                sig_header = (
                    request.headers.get("X-Hub-Signature-256")
                    or request.headers.get("X-ClawClip-Signature")
                    or ""
                )
                if not self._verify_signature(raw_body, sig_header):
                    logger.warning("Webhook %s: invalid signature", webhook_id)
                    raise HTTPException(status_code=401, detail="Invalid webhook signature")

            try:
                payload = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body")

            headers = dict(request.headers)
            # Route by registered path using the webhook_id as the path key.
            result = await self._router.route(
                f"/{webhook_id}", headers, payload
            )

            status_code = 200 if result.get("status") != "error" else 422
            return JSONResponse(result, status_code=status_code)

        return api

    # ── internal helpers ──────────────────────────────────────────

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        """Return True if *signature* matches HMAC-SHA256 of *body*."""
        if not self._secret:
            return True
        expected = (
            "sha256="
            + hmac.new(
                self._secret.encode(),
                body,
                hashlib.sha256,
            ).hexdigest()
        )
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def _route_to_dict(route: WebhookRoute) -> dict:
        return {
            "id": route.id,
            "path": route.path,
            "parser": route.parser,
            "action_type": route.action_type,
            "action_config": route.action_config,
        }
