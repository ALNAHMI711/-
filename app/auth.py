"""Authentication primitives for the Mashahid control plane.

This module deliberately keeps authentication independent from HTTP and storage.
Passwords are hashed with Argon2id; sessions contain only opaque random tokens.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError


_password_hasher = PasswordHasher()


class AuthenticationError(ValueError):
    """Raised when credentials or a session are invalid."""


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not isinstance(password, str) or not isinstance(password_hash, str):
        return False
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


@dataclass(frozen=True)
class Session:
    session_id: str
    user_id: str
    expires_at: datetime


class InMemorySessionStore:
    """Development/test session store; production should use durable storage."""

    def __init__(self) -> None:
        self._sessions: dict[str, tuple[str, str, datetime]] = {}

    @staticmethod
    def session_id_for_token(token: str) -> str:
        if not isinstance(token, str) or not token:
            raise ValueError("token is required")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create(self, user_id: str, ttl_seconds: int = 3600) -> Session:
        session, _ = self.create_with_token(user_id, ttl_seconds)
        return session

    def create_with_token(self, user_id: str, ttl_seconds: int = 3600) -> tuple[Session, str]:
        if not user_id.strip():
            raise ValueError("user_id is required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        token = secrets.token_urlsafe(32)
        session_id = self.session_id_for_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        self._sessions[session_id] = (user_id, token, expires_at)
        return Session(session_id, user_id, expires_at), token

    def validate(self, session_id: str, token: str, now: datetime | None = None) -> Session:
        record = self._sessions.get(session_id)
        if record is None:
            raise AuthenticationError("invalid session")
        user_id, expected_token, expires_at = record
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if current >= expires_at or not hmac.compare_digest(expected_token, token):
            self.revoke(session_id)
            raise AuthenticationError("invalid session")
        return Session(session_id, user_id, expires_at)

    def validate_token(self, token: str, now: datetime | None = None) -> Session:
        return self.validate(self.session_id_for_token(token), token, now)

    def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def revoke_token(self, token: str) -> None:
        self.revoke(self.session_id_for_token(token))

    def revoke_all(self, user_id: str) -> None:
        for session_id, (owner, _, _) in list(self._sessions.items()):
            if owner == user_id:
                self._sessions.pop(session_id, None)
