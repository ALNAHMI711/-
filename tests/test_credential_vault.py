from datetime import datetime, timedelta, timezone

import pytest

from app.credential_vault import CredentialRef, InMemoryCredentialVault


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
