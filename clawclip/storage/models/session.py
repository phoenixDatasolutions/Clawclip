"""LLMSession model — provider-agnostic session tracking."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from clawclip.storage.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, _utcnow


class LLMSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An LLM session (provider-agnostic, replaces ClaudeSession)."""
    __tablename__ = "llm_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    provider_session_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255))
    working_directory: Mapped[str | None] = mapped_column(String(1024))
    allowed_tools: Mapped[list | None] = mapped_column(JSON)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict | None] = mapped_column(JSON)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_turns: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
