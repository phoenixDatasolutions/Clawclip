"""User and UserPlatformLink models."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clawclip.storage.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Platform-agnostic user. One User can be linked to many platforms."""
    __tablename__ = "users"

    display_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    platform_links: Mapped[list[UserPlatformLink]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserPlatformLink(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Links a User to a specific platform identity."""
    __tablename__ = "user_platform_links"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_platform_user"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(50))
    platform_user_id: Mapped[str] = mapped_column(String(255))
    platform_username: Mapped[str | None] = mapped_column(String(255))
    platform_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    user: Mapped[User] = relationship(back_populates="platform_links")
