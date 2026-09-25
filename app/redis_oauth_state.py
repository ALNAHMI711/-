"""Shared, expiring OAuth state storage backed by Redis."""

from secrets import compare_digest, token_urlsafe
import time

import redis

from .oauth_session import OAuthState

_CREATE = """
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2], 'NX')
return redis.call('GET', KEYS[1])
"""

_CONSUME = """
local value = redis.call('GET', KEYS[1])
if not value then return 0 end
if value ~= ARGV[1] then return 0 end
redis.call('DEL', KEYS[1])
return 1
"""


class RedisOAuthStateStore:
    """Redis implementation with single-use consumption and TTL enforcement."""

    def __init__(self, client: redis.Redis, ttl_seconds: int = 600, prefix: str = "mashahid:oauth:") -> None:
        if ttl_seconds <= 0 or not prefix:
            raise ValueError("valid ttl_seconds and prefix are required")
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._prefix = prefix

    def create(
        self,
        platform: str,
        now: float | None = None,
        *,
        user_id: str = "",
        project_id: str = "",
    ) -> OAuthState:
        timestamp = time.time() if now is None else now
        platform = platform.strip().lower()
        user_id = user_id.strip()
        project_id = project_id.strip()
        if not platform:
            raise ValueError("platform is required")
        if bool(user_id) != bool(project_id):
            raise ValueError("user_id and project_id must be provided together")

        state = OAuthState(
            value=token_urlsafe(32),
            created_at=timestamp,
            expires_at=timestamp + self._ttl_seconds,
            platform=platform,
            user_id=user_id,
            project_id=project_id,
        )
        payload = "\x1f".join((state.platform, state.user_id, state.project_id, str(state.created_at)))
        key = f"{self._prefix}{state.value}"
        stored = self._client.eval(_CREATE, 1, key, payload, self._ttl_seconds)
        if stored is None:
            raise RuntimeError("unable to create unique OAuth state")
        return state

    def get(self, value: str, now: float | None = None) -> OAuthState | None:
        timestamp = time.time() if now is None else now
        if not value.strip():
            return None
        payload = self._client.get(f"{self._prefix}{value}")
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        parts = payload.split("\x1f")
        if len(parts) != 4:
            return None
        platform, user_id, project_id, created_text = parts
        try:
            created_at = float(created_text)
        except ValueError:
            return None
        state = OAuthState(
            value=value,
            created_at=created_at,
            expires_at=created_at + self._ttl_seconds,
            platform=platform,
            user_id=user_id,
            project_id=project_id,
        )
        return state if timestamp <= state.expires_at else None

    def consume(self, expected: OAuthState, received: str, now: float | None = None) -> bool:
        timestamp = time.time() if now is None else now
        if timestamp > expected.expires_at:
            self._client.delete(f"{self._prefix}{expected.value}")
            return False
        if not compare_digest(expected.value, received):
            return False
        stored = self.get(expected.value, now=timestamp)
        if stored is None:
            return False
        if (
            stored.platform != expected.platform
            or stored.user_id != expected.user_id
            or stored.project_id != expected.project_id
        ):
            return False
        return bool(
            self._client.eval(
                _CONSUME,
                1,
                f"{self._prefix}{expected.value}",
                "\x1f".join((expected.platform, expected.user_id, expected.project_id, str(expected.created_at))),
            )
        )

    def purge_expired(self, now: float | None = None) -> int:
        # Redis TTL handles expiry; no scan/delete is required.
        return 0
