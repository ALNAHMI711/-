"""Durable PostgreSQL-backed authentication sessions."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .auth import AuthenticationError, Session


class PostgresSessionStore:
    """Production session store; only a token hash is persisted."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN is required")
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    @staticmethod
    def session_id_for_token(token: str) -> str:
        if not isinstance(token, str) or not token:
            raise ValueError("token is required")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_with_token(self, user_id: str, ttl_seconds: int = 3600) -> tuple[Session, str]:
        if not user_id.strip() or ttl_seconds <= 0:
            raise ValueError("user_id and positive ttl_seconds are required")
        token = secrets.token_urlsafe(32)
        session_id = self.session_id_for_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (session_id,user_id,expires_at) VALUES (%s,%s,%s)",
                (session_id, user_id.strip(), expires_at),
            )
        return Session(session_id, user_id.strip(), expires_at), token

    def validate_token(self, token: str, now: datetime | None = None) -> Session:
        session_id = self.session_id_for_token(token)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT session_id,user_id,expires_at FROM sessions WHERE session_id=%s",
                (session_id,),
            )
            row: dict[str, Any] | None = cur.fetchone()
            if row is None or current >= row["expires_at"]:
                if row is not None:
                    cur.execute("DELETE FROM sessions WHERE session_id=%s", (session_id,))
                raise AuthenticationError("invalid session")
            # session_id is derived from the supplied bearer token, so no raw token
            # comparison or token persistence is required.
            if not hmac.compare_digest(session_id, self.session_id_for_token(token)):
                raise AuthenticationError("invalid session")
            return Session(row["session_id"], row["user_id"], row["expires_at"])

    def revoke_token(self, token: str) -> None:
        self.revoke(self.session_id_for_token(token))

    def revoke(self, session_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE session_id=%s", (session_id,))

    def revoke_all(self, user_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE user_id=%s", (user_id.strip(),))
