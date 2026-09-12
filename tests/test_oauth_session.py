import pytest

from app.oauth_session import OAuthStateStore


def test_state_is_single_use_and_platform_bound():
    store = OAuthStateStore(ttl_seconds=60)
    state = store.create("YouTube", now=100.0)

    assert store.consume(state, state.value, now=101.0)
    assert not store.consume(state, state.value, now=102.0)


def test_state_rejects_wrong_value_platform_and_expiry():
    store = OAuthStateStore(ttl_seconds=10)
    state = store.create("youtube", now=100.0)

    assert not store.consume(state, state.value, now=111.0)
    other = store.create("tiktok", now=100.0)
    assert not store.consume(other, state.value, now=101.0)


def test_invalid_ttl_is_rejected():
    with pytest.raises(ValueError):
        OAuthStateStore(ttl_seconds=0)


def test_purge_expired_returns_count():
    store = OAuthStateStore(ttl_seconds=10)
    store.create("youtube", now=100.0)
    store.create("tiktok", now=105.0)

    assert store.purge_expired(now=111.0) == 1
    assert store.purge_expired(now=116.0) == 1
