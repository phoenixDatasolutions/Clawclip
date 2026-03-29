"""EncryptedCredential model — encrypted storage for API keys and secrets."""

from __future__ import annotations

from sqlalchemy import LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from nexusai.storage.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EncryptedCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Encrypted storage for API keys and secrets."""
    __tablename__ = "encrypted_credentials"
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", "key_name", name="uq_credential"),
    )

    owner_type: Mapped[str] = mapped_column(String(50))  # user, agent, skill, system
    owner_id: Mapped[str] = mapped_column(String(36))
    key_name: Mapped[str] = mapped_column(String(255))
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary)
