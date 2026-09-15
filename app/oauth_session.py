"""Session-bound OAuth state storage primitives.

The store keeps only short-lived OAuth state metadata. Provider tokens and
client secrets are deliberately outside this module.
"""

from dataclasses import dataclass
from secrets import compare_digest, token_urlsafe
import time


@dataclass(frozen=True)
class OAuthState:
    value: str
    created_at: float
    expires_at: float
    platform: str
    user_id: str = ""
    project_id: str = ""


class OAuthStateStore:
    """Small in-memory state store suitable for tests/development.

    Production deployments should back this contract with a shared, expiring
    server-side store such as Redis so callbacks work across worker instances.
    """

    def __init__(self, ttl_seconds: int = 600) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._states: dict[str, OAuthState] = {}

    def create(
        self,
        platform: str,
        now: float | None = None,
        *,
        user_id: str = "",
        project_id: str = "",
    ) -> OAuthState:
        timestamp = time.time() if now is None else now
        normalized_platform = platform.strip().lower()
        if not normalized_platform:
            raise ValueError("platform is required")
        if bool(user_id.strip()) != bool(project_id.strip()):
            raise ValueError("user_id and project_id must be provided together")
        value = token_urlsafe(32)
        state = OAuthState(
            value=value,
            created_at=timestamp,
            expires_at=timestamp + self._ttl_seconds,
            platform=normalized_platform,
            user_id=user_id.strip(),
            project_id=project_id.strip(),
        )
        self._states[value] = state
        return state

    def consume(self, expected: OAuthState, received: str, now: float | None = None) -> bool:
        timestamp = time.time() if now is None else now
        stored = self._states.pop(expected.value, None)
        if stored is None or timestamp > stored.expires_at:
            return False
        if stored.platform != expected.platform:
            return False
        if stored.user_id != expected.user_id or stored.project_id != expected.project_id:
            return False
        return compare_digest(stored.value, received)

    def get(self, value: str, now: float | None = None) -> OAuthState | None:
        timestamp = time.time() if now is None else now
        state = self._states.get(value)
        if state is None or timestamp > state.expires_at:
            return None
        return state

    def purge_expired(self, now: float | None = None) -> int:
        timestamp = time.time() if now is None else now
        expired = [key for key, state in self._states.items() if timestamp > state.expires_at]
        for key in expired:
            del self._states[key]
        return len(expired)
