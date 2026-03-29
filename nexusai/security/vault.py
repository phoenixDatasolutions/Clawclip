"""Fernet-encrypted credential vault backed by the EncryptedCredential model."""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusai.storage.models.credential import EncryptedCredential

logger = logging.getLogger(__name__)

_SYSTEM_OWNER_TYPE = "system"
_SYSTEM_OWNER_ID = "nexusai"


class CredentialVault:
    """Encrypts, stores, and retrieves secrets using Fernet symmetric encryption.

    All credentials are stored in the `encrypted_credentials` table under
    owner_type="system", owner_id="nexusai" by default.
    """

    def __init__(self, master_key: bytes | None = None) -> None:
        if master_key is None:
            master_key = Fernet.generate_key()
            logger.warning(
                "CredentialVault: no master_key provided — generated ephemeral key. "
                "Credentials will not survive restarts."
            )
        self._fernet = Fernet(master_key)

    # ── Crypto helpers ──────────────────────────────────────────

    def encrypt(self, plaintext: str) -> bytes:
        """Return Fernet-encrypted bytes for the given plaintext."""
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt Fernet-encrypted bytes and return the plaintext string."""
        return self._fernet.decrypt(ciphertext).decode()

    # ── Persistence ─────────────────────────────────────────────

    async def store(self, name: str, value: str, session: AsyncSession) -> None:
        """Encrypt `value` and upsert it under `name` in the database."""
        encrypted = self.encrypt(value)
        stmt = select(EncryptedCredential).where(
            EncryptedCredential.owner_type == _SYSTEM_OWNER_TYPE,
            EncryptedCredential.owner_id == _SYSTEM_OWNER_ID,
            EncryptedCredential.key_name == name,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.encrypted_value = encrypted
        else:
            session.add(
                EncryptedCredential(
                    owner_type=_SYSTEM_OWNER_TYPE,
                    owner_id=_SYSTEM_OWNER_ID,
                    key_name=name,
                    encrypted_value=encrypted,
                )
            )
        await session.flush()
        logger.debug("Vault: stored credential %r", name)

    async def retrieve(self, name: str, session: AsyncSession) -> str | None:
        """Return the decrypted value for `name`, or None if not found."""
        stmt = select(EncryptedCredential).where(
            EncryptedCredential.owner_type == _SYSTEM_OWNER_TYPE,
            EncryptedCredential.owner_id == _SYSTEM_OWNER_ID,
            EncryptedCredential.key_name == name,
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self.decrypt(record.encrypted_value)

    async def delete(self, name: str, session: AsyncSession) -> None:
        """Remove the credential with `name` from the database."""
        stmt = select(EncryptedCredential).where(
            EncryptedCredential.owner_type == _SYSTEM_OWNER_TYPE,
            EncryptedCredential.owner_id == _SYSTEM_OWNER_ID,
            EncryptedCredential.key_name == name,
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is not None:
            await session.delete(record)
            await session.flush()
        logger.debug("Vault: deleted credential %r", name)

    async def list_names(self, session: AsyncSession) -> list[str]:
        """Return all credential names stored in the vault."""
        stmt = select(EncryptedCredential.key_name).where(
            EncryptedCredential.owner_type == _SYSTEM_OWNER_TYPE,
            EncryptedCredential.owner_id == _SYSTEM_OWNER_ID,
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
