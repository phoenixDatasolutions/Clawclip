"""Dashboard conversation history endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from clawclip.dashboard.auth import JWTBearer

logger = logging.getLogger(__name__)


# ── Response Models ───────────────────────────────────────────────


class ConversationSummary(BaseModel):
    conv_id: str
    user_id: str
    platform: str
    channel_id: str
    title: str | None
    is_active: bool
    created_at: str
    updated_at: str | None = None
    message_count: int = 0


class MessageSummary(BaseModel):
    message_id: str
    role: str
    content: str
    agent_id: str | None = None
    provider: str | None = None
    model: str | None = None
    cost_usd: float | None = None
    token_count: int | None = None
    created_at: str


class PaginatedConversations(BaseModel):
    items: list[ConversationSummary]
    total: int
    page: int
    limit: int


class ConversationDetail(BaseModel):
    conversation: ConversationSummary
    messages: list[MessageSummary]


# ── Router Factory ────────────────────────────────────────────────


def create_conversations_router(nexus_app: Any = None) -> APIRouter:
    """Return an APIRouter with conversation history endpoints."""

    _router = APIRouter(prefix="/api/conversations", tags=["conversations"])

    def _config_get(key: str, default: Any = None) -> Any:
        if nexus_app is not None and hasattr(nexus_app, "config"):
            return nexus_app.config.get(key, default)
        return default

    jwt_secret: str = _config_get("dashboard.jwt_secret", "change-me-in-local-yaml")
    bearer = JWTBearer(secret=jwt_secret)

    @_router.get("", response_model=PaginatedConversations)
    async def list_conversations(
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=200),
        platform: str | None = Query(None),
        _claims: dict[str, Any] = Depends(bearer),
    ) -> PaginatedConversations:
        """List conversations with pagination and optional platform filter."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return PaginatedConversations(items=[], total=0, page=page, limit=limit)
        try:
            from sqlalchemy import func, select
            from clawclip.storage.models.conversation import Conversation, ConversationMessage

            offset = (page - 1) * limit
            async with nexus_app.db.session() as session:
                stmt = select(Conversation)
                if platform:
                    stmt = stmt.where(Conversation.platform == platform)
                total_row = await session.execute(
                    select(func.count()).select_from(stmt.subquery())
                )
                total: int = total_row.scalar_one()

                rows = (
                    await session.execute(
                        stmt.order_by(Conversation.created_at.desc()).offset(offset).limit(limit)
                    )
                ).scalars().all()

                items = []
                for r in rows:
                    count_row = await session.execute(
                        select(func.count(ConversationMessage.id)).where(
                            ConversationMessage.conversation_id == r.id
                        )
                    )
                    msg_count: int = count_row.scalar_one()
                    items.append(_conv_to_summary(r, msg_count))

            return PaginatedConversations(items=items, total=total, page=page, limit=limit)
        except Exception as exc:
            logger.exception("Failed to list conversations")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.get("/{conv_id}", response_model=ConversationDetail)
    async def get_conversation(
        conv_id: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> ConversationDetail:
        """Get a conversation with all its messages."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available",
            )
        try:
            from sqlalchemy import select
            from clawclip.storage.models.conversation import Conversation

            async with nexus_app.db.session() as session:
                row = (
                    await session.execute(
                        select(Conversation).where(Conversation.id == conv_id)
                    )
                ).scalar_one_or_none()
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Conversation '{conv_id}' not found",
                    )
                messages = [_msg_to_summary(m) for m in row.messages]
                summary = _conv_to_summary(row, len(messages))

            return ConversationDetail(conversation=summary, messages=messages)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to get conversation %s", conv_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.delete("/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_conversation(
        conv_id: str,
        _claims: dict[str, Any] = Depends(bearer),
    ) -> None:
        """Delete a conversation and all its messages."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available",
            )
        try:
            from sqlalchemy import select
            from clawclip.storage.models.conversation import Conversation

            async with nexus_app.db.session() as session:
                row = (
                    await session.execute(
                        select(Conversation).where(Conversation.id == conv_id)
                    )
                ).scalar_one_or_none()
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Conversation '{conv_id}' not found",
                    )
                await session.delete(row)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to delete conversation %s", conv_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @_router.get("/{conv_id}/messages")
    async def list_messages(
        conv_id: str,
        page: int = Query(1, ge=1),
        limit: int = Query(50, ge=1, le=500),
        _claims: dict[str, Any] = Depends(bearer),
    ) -> dict[str, Any]:
        """Get messages for a conversation with pagination."""
        if nexus_app is None or not hasattr(nexus_app, "db"):
            return {"items": [], "total": 0, "page": page, "limit": limit}
        try:
            from sqlalchemy import func, select
            from clawclip.storage.models.conversation import ConversationMessage

            offset = (page - 1) * limit
            async with nexus_app.db.session() as session:
                total_row = await session.execute(
                    select(func.count(ConversationMessage.id)).where(
                        ConversationMessage.conversation_id == conv_id
                    )
                )
                total: int = total_row.scalar_one()
                rows = (
                    await session.execute(
                        select(ConversationMessage)
                        .where(ConversationMessage.conversation_id == conv_id)
                        .order_by(ConversationMessage.created_at)
                        .offset(offset)
                        .limit(limit)
                    )
                ).scalars().all()
            return {
                "items": [_msg_to_summary(r).model_dump() for r in rows],
                "total": total,
                "page": page,
                "limit": limit,
            }
        except Exception as exc:
            logger.exception("Failed to list messages for conversation %s", conv_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    return _router


# ── Shared Helpers ────────────────────────────────────────────────


def _conv_to_summary(row: Any, message_count: int = 0) -> ConversationSummary:
    return ConversationSummary(
        conv_id=row.id,
        user_id=row.user_id,
        platform=row.platform,
        channel_id=row.channel_id,
        title=row.title,
        is_active=row.is_active,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if getattr(row, "updated_at", None) else None,
        message_count=message_count,
    )


def _msg_to_summary(row: Any) -> MessageSummary:
    return MessageSummary(
        message_id=row.id,
        role=row.role,
        content=row.content,
        agent_id=row.agent_id,
        provider=row.provider,
        model=row.model,
        cost_usd=row.cost_usd,
        token_count=row.token_count,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )
