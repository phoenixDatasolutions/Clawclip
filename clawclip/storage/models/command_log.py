"""CommandLog model — audit trail for all executed commands."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from clawclip.storage.models.base import Base, UUIDPrimaryKeyMixin, _utcnow


class CommandLog(Base, UUIDPrimaryKeyMixin):
    """Audit trail for all executed commands/actions."""
    __tablename__ = "command_logs"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(50))
    command_type: Mapped[str] = mapped_column(String(50))
    command_text: Mapped[str] = mapped_column(Text)
    response_summary: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[str | None] = mapped_column(String(36))
    skill_name: Mapped[str | None] = mapped_column(String(100))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="success")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
