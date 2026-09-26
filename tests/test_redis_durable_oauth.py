from datetime import datetime, timedelta, timezone
import os

import pytest
import redis

from app.account_provider import ProviderAccount
from app.credential_vault import CredentialRef
from app.redis_credential_vault import RedisCredentialVault
from app.redis_pending_account_selection import RedisPendingAccountSelectionStore


@pytest.fixture()
def redis_client():
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = redis.from_url(url)
    try:
        client.ping()
    except redis.RedisError:
        pytest.skip("Redis is not available")
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()


def test_redis_credential_vault_encrypts_and_round_trips(redis_client):
    vault = RedisCredentialVault(redis_client, b"0123456789abcdef0123456789abcdef")
    ref = vault.put(
        platform="YouTube", account_id="yt-1", access_token="access-secret",
        refresh_token="refresh-secret", scopes=("b", "a"),
    )
    raw = redis_client.get("mashahid:credentials:" + ref.credential_id)
    assert raw is not None
    assert b"access-secret" not in raw
    assert b"refresh-secret" not in raw
    assert vault.get_secret(ref) == ("access-secret", "refresh-secret")


def test_redis_credential_vault_rejects_tampering(redis_client):
    vault = RedisCredentialVault(redis_client, b"0123456789abcdef0123456789abcdef")
    ref = vault.put(platform="youtube", account_id="yt-2", access_token="secret")
    key = "mashahid:credentials:" + ref.credential_id
    raw = redis_client.get(key)
    assert raw is not None
    redis_client.set(key, raw.replace(b"ciphertext", b"ciphertextX"))
    with pytest.raises((PermissionError, KeyError)):
        vault.get_secret(ref)


def test_redis_pending_selection_is_single_use_and_project_bound(redis_client):
    vault = RedisCredentialVault(redis_client, b"0123456789abcdef0123456789abcdef")
    ref = vault.put(platform="youtube", account_id="yt-1", access_token="secret")
    store = RedisPendingAccountSelectionStore(redis_client, ttl_seconds=600)
    item = store.create(
        user_id="admin", project_id="p1", platform="youtube",
        credential=ref,
        accounts=(
            ProviderAccount("yt-1", "One"),
            ProviderAccount("yt-2", "Two"),
        ),
    )
    selected = store.consume(
        item.selection_token, user_id="admin", project_id="p1", account_id="yt-2"
    )
    assert selected.credential == ref
    with pytest.raises(ValueError):
        store.consume(
            item.selection_token, user_id="admin", project_id="p1", account_id="yt-1"
        )


def test_redis_pending_selection_expires(redis_client):
    vault = RedisCredentialVault(redis_client, b"0123456789abcdef0123456789abcdef")
    ref = vault.put(platform="youtube", account_id="yt-3", access_token="secret")
    store = RedisPendingAccountSelectionStore(redis_client, ttl_seconds=1)
    now = datetime.now(timezone.utc)
    item = store.create(
        user_id="admin", project_id="p1", platform="youtube",
        credential=ref, accounts=(ProviderAccount("yt-3", "Three"),), now=now,
    )
    with pytest.raises(ValueError):
        store.consume(
            item.selection_token, user_id="admin", project_id="p1",
            account_id="yt-3", now=now + timedelta(seconds=2),
        )
