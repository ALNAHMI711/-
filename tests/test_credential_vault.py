from datetime import datetime, timedelta, timezone

import pytest

from app.credential_vault import CredentialRef, InMemoryCredentialVault


def test_reference_contains_metadata_but_not_secret():
    vault = InMemoryCredentialVault()
    ref = vault.put(
        platform="YouTube",
        account_id="yt-1",
        access_token="ACCESS-SECRET",
        refresh_token="REFRESH-SECRET",
        scopes=("youtube.upload",),
    )

    assert isinstance(ref, CredentialRef)
    assert ref.platform == "youtube"
    assert ref.account_id == "yt-1"
    assert ref.refreshable
    assert "SECRET" not in repr(ref)
    assert "ACCESS" not in repr(ref)


def test_secret_can_only_be_retrieved_by_matching_reference():
    vault = InMemoryCredentialVault()
    ref = vault.put(platform="youtube", account_id="yt-1", access_token="ACCESS-SECRET")

    assert vault.get_secret(ref) == ("ACCESS-SECRET", None)
    with pytest.raises(KeyError):
        vault.get_secret(CredentialRef("cred_missing", "youtube", "yt-1", ()))


def test_expired_credentials_are_rejected():
    vault = InMemoryCredentialVault()
    ref = vault.put(
        platform="youtube",
        account_id="yt-1",
        access_token="ACCESS-SECRET",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with pytest.raises(PermissionError):
        vault.get_secret(ref)


def test_naive_expiry_is_rejected():
    vault = InMemoryCredentialVault()
    with pytest.raises(ValueError):
        vault.put(
            platform="youtube",
            account_id="yt-1",
            access_token="ACCESS-SECRET",
            expires_at=datetime.now(),
        )


def test_delete_removes_secret():
    vault = InMemoryCredentialVault()
    ref = vault.put(platform="youtube", account_id="yt-1", access_token="ACCESS-SECRET")
    vault.delete(ref)

    with pytest.raises(KeyError):
        vault.get_secret(ref)
