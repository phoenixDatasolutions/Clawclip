"""Unit tests for clawclip.security.vault — CredentialVault."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from clawclip.security.vault import CredentialVault


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_vault() -> CredentialVault:
    """Return a CredentialVault with a fixed test key."""
    key = Fernet.generate_key()
    return CredentialVault(master_key=key)


def _mock_session() -> MagicMock:
    """Return an async mock that mimics AsyncSession behaviour."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()
    return session


# ── test_encrypt_decrypt_roundtrip ────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip() -> None:
    """encrypt() then decrypt() returns the original plaintext."""
    vault = _make_vault()
    original = "super-secret-api-key"
    ciphertext = vault.encrypt(original)
    assert vault.decrypt(ciphertext) == original


# ── test_different_values_differ ─────────────────────────────────────────────


def test_different_values_differ() -> None:
    """Two different plaintext values produce different ciphertext."""
    vault = _make_vault()
    ct1 = vault.encrypt("value-one")
    ct2 = vault.encrypt("value-two")
    assert ct1 != ct2


# ── test_same_value_differs_each_time ────────────────────────────────────────


def test_same_value_differs_each_time() -> None:
    """Fernet uses a random IV — encrypting the same value twice yields different bytes."""
    vault = _make_vault()
    ct1 = vault.encrypt("same-secret")
    ct2 = vault.encrypt("same-secret")
    # Both decrypt correctly but ciphertexts should differ
    assert ct1 != ct2
    assert vault.decrypt(ct1) == vault.decrypt(ct2) == "same-secret"


# ── test_store_and_retrieve ───────────────────────────────────────────────────


async def test_store_and_retrieve() -> None:
    """store() then retrieve() returns the original plaintext."""
    vault = _make_vault()
    session = _mock_session()

    # store() tries to look up existing record first — return None (not found)
    from clawclip.security.vault import EncryptedCredential

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    await vault.store("api_key", "sk-123", session)
    session.add.assert_called_once()

    # Now simulate retrieve() — return the just-stored object
    stored_obj = MagicMock(spec=EncryptedCredential)
    stored_obj.encrypted_value = vault.encrypt("sk-123")
    mock_result_retrieve = MagicMock()
    mock_result_retrieve.scalar_one_or_none.return_value = stored_obj
    session.execute.return_value = mock_result_retrieve

    result = await vault.retrieve("api_key", session)
    assert result == "sk-123"


# ── test_retrieve_missing ─────────────────────────────────────────────────────


async def test_retrieve_missing() -> None:
    """retrieve() returns None when the credential does not exist."""
    vault = _make_vault()
    session = _mock_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    result = await vault.retrieve("nonexistent", session)
    assert result is None


# ── test_delete ───────────────────────────────────────────────────────────────


async def test_delete() -> None:
    """After delete(), retrieve() returns None."""
    vault = _make_vault()
    session = _mock_session()

    # Simulate an existing record
    from clawclip.security.vault import EncryptedCredential

    stored_obj = MagicMock(spec=EncryptedCredential)
    stored_obj.encrypted_value = vault.encrypt("to-be-deleted")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stored_obj
    session.execute.return_value = mock_result

    await vault.delete("my_key", session)
    session.delete.assert_called_once_with(stored_obj)
    session.flush.assert_called()


# ── test_delete_missing_no_error ──────────────────────────────────────────────


async def test_delete_missing_no_error() -> None:
    """Deleting a non-existent credential must not raise."""
    vault = _make_vault()
    session = _mock_session()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    await vault.delete("ghost", session)  # must not raise
    session.delete.assert_not_called()


# ── test_list_names ───────────────────────────────────────────────────────────


async def test_list_names() -> None:
    """list_names() returns credential key names only (not their values)."""
    vault = _make_vault()
    session = _mock_session()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = ["api_key", "db_pass", "smtp_pass"]
    session.execute.return_value = mock_result

    names = await vault.list_names(session)
    assert set(names) == {"api_key", "db_pass", "smtp_pass"}


# ── test_store_updates_existing ───────────────────────────────────────────────


async def test_store_updates_existing() -> None:
    """store() overwrites encrypted_value when the credential already exists."""
    vault = _make_vault()
    session = _mock_session()

    from clawclip.security.vault import EncryptedCredential

    existing = MagicMock(spec=EncryptedCredential)
    existing.encrypted_value = vault.encrypt("old-value")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    session.execute.return_value = mock_result

    await vault.store("api_key", "new-value", session)

    # add() must NOT be called — existing record was updated in place
    session.add.assert_not_called()
    # The encrypted_value attribute should have been set to the new ciphertext
    assert existing.encrypted_value != vault.encrypt("old-value")  # new bytes
    assert vault.decrypt(existing.encrypted_value) == "new-value"
