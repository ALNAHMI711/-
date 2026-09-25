from datetime import datetime, timedelta, timezone

import pytest

from app.credential_vault import CredentialRef, EncryptedMemoryCredentialVault, InMemoryCredentialVault


def test_reference_is_opaque_and_excludes_raw_token():
    vault = InMemoryCredentialVault()
    ref = vault.put(
        platform="YouTube",
        account_id="yt-1",
        access_token="token-value-for-test",
        refresh_token="refresh-value-for-test",
        scopes=("youtube.upload",),
    )

    assert isinstance(ref, CredentialRef)
    assert ref.platform == "youtube"
    assert ref.account_id == "yt-1"
    assert ref.refreshable is True
    assert "token-value-for-test" not in repr(ref)
    assert "refresh-value-for-test" not in repr(ref)


def test_matching_reference_retrieves_transient_secret_and_delete_revokes_it():
    vault = InMemoryCredentialVault()
    ref = vault.put(platform="youtube", account_id="yt-1", access_token="token-value")

    assert vault.get_secret(ref) == ("token-value", None)
    vault.delete(ref)
    with pytest.raises(KeyError):
        vault.get_secret(ref)


def test_expired_and_naive_expiry_values_are_rejected():
    vault = InMemoryCredentialVault()
    expired = vault.put(
        platform="youtube",
        account_id="yt-1",
        access_token="token-value",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(PermissionError):
        vault.get_secret(expired)

    with pytest.raises(ValueError):
        vault.put(
            platform="youtube",
            account_id="yt-2",
            access_token="token-value",
            expires_at=datetime.now(),
        )


def test_encrypted_vault_round_trip_and_metadata_only_ref():
    vault = EncryptedMemoryCredentialVault(b"0123456789abcdef0123456789abcdef")
    ref = vault.put(
        platform="YouTube",
        account_id="channel-1",
        access_token="access-secret",
        refresh_token="refresh-secret",
        scopes=("b", "a", "a"),
    )

    assert ref.platform == "youtube"
    assert ref.scopes == ("a", "b")
    assert "access-secret" not in repr(ref)
    assert "refresh-secret" not in repr(ref)
    assert vault.get_secret(ref) == ("access-secret", "refresh-secret")


def test_encrypted_vault_rejects_invalid_master_key():
    with pytest.raises(ValueError):
        EncryptedMemoryCredentialVault(b"too-short")


def test_encrypted_vault_rejects_tampered_ciphertext():
    vault = EncryptedMemoryCredentialVault(b"0123456789abcdef0123456789abcdef")
    ref = vault.put(platform="tiktok", account_id="user-1", access_token="secret")
    stored_ref, nonce, ciphertext = vault._records[ref.credential_id]
    vault._records[ref.credential_id] = (
        stored_ref,
        nonce,
        ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]),
    )

    with pytest.raises(Exception):
        vault.get_secret(ref)


def test_encrypted_vault_rejects_expired_credential():
    vault = EncryptedMemoryCredentialVault(b"0123456789abcdef0123456789abcdef")
    ref = vault.put(
        platform="linkedin",
        account_id="member-1",
        access_token="secret",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with pytest.raises(PermissionError):
        vault.get_secret(ref)


def test_encrypted_vault_delete_removes_secret():
    vault = EncryptedMemoryCredentialVault(b"0123456789abcdef0123456789abcdef")
    ref = vault.put(platform="youtube", account_id="channel-2", access_token="secret")
    vault.delete(ref)

    with pytest.raises(KeyError):
        vault.get_secret(ref)
