"""AgentInstance and AgentRun models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexusai.storage.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, _utcnow


class AgentInstance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A running or historical agent instance."""
    __tablename__ = "agent_instances"

    agent_type: Mapped[str] = mapped_column(String(100))
    parent_agent_id: Mapped[str | None] = mapped_column(String(36))
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="idle")
    config: Mapped[dict | None] = mapped_column(JSON)
    state: Mapped[dict | None] = mapped_column(JSON)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    runs: Mapped[list[AgentRun]] = relationship(back_populates="agent_instance", cascade="all, delete-orphan")


class AgentRun(Base, UUIDPrimaryKeyMixin):
    """A single execution run of an agent."""
    __tablename__ = "agent_runs"

    agent_instance_id: Mapped[str] = mapped_column(ForeignKey("agent_instances.id"), index=True)
    task_description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="running")
    result_summary: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent_instance: Mapped[AgentInstance] = relationship(back_populates="runs")
