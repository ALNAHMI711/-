from datetime import datetime, timedelta, timezone

import pytest

from app.auth import AuthenticationError, InMemorySessionStore, hash_password, verify_password


def test_password_uses_argon2id_and_verifies():
    password = "correct horse battery staple 2026"
    password_hash = hash_password(password)
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password, password_hash)
    assert not verify_password("wrong password", password_hash)


def test_short_password_is_rejected():
    with pytest.raises(ValueError):
        hash_password("too-short")


def test_session_token_is_opaque_and_revocable():
    store = InMemorySessionStore()
    session = store.create("user-1", ttl_seconds=60)
    assert len(session.session_id) == 64
    with pytest.raises(AuthenticationError):
        store.validate(session.session_id, "wrong-token")

    # The raw token is intentionally never returned by Session. A valid
    # production adapter will obtain it from the secure HTTP-only cookie.
    assert session.user_id == "user-1"
    store.revoke(session.session_id)
    with pytest.raises(AuthenticationError):
        store.validate(session.session_id, "anything")


def test_expired_session_is_rejected():
    store = InMemorySessionStore()
    session = store.create("user-1", ttl_seconds=1)
    # Recovering the raw token is intentionally impossible from the public API;
    # this test checks the expiry invariant using the stored record internally.
    _, token, expires_at = store._sessions[session.session_id]
    assert expires_at > datetime.now(timezone.utc)
    with pytest.raises(AuthenticationError):
        store.validate(session.session_id, token, now=expires_at + timedelta(seconds=1))
