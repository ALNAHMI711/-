"""Production Redis lease adapter.

Redis is coordination only; PostgreSQL remains the source of truth for durable
job state. Redis stores only an opaque lease token, never platform credentials.
"""

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

import redis

from .redis_coordination import Lease, LeaseNotOwned

_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


class RedisLeaseCoordinator:
    """Redis-backed atomic lease coordinator using opaque ownership tokens."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def acquire(self, key: str, owner: str, ttl_seconds: int, now: datetime | None = None) -> Lease:
        if not key.strip() or not owner.strip() or ttl_seconds <= 0:
            raise ValueError("valid key, owner and ttl_seconds are required")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        token = token_urlsafe(32)
        if not self._client.set(key, token, nx=True, ex=ttl_seconds):
            raise LeaseNotOwned("lease is already held")
        return Lease(key, owner, token, current + timedelta(seconds=ttl_seconds))

    def acquire_job(self, key: str, owner: str, ttl_seconds: int,
                    now: datetime | None = None) -> Lease:
        """Common control-plane boundary for acquiring an opaque job lease."""
        return self.acquire(key, owner, ttl_seconds, now=now)

    def renew(self, lease: Lease, ttl_seconds: int, now: datetime | None = None) -> Lease:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        result = self._client.eval(_RENEW, 1, lease.key, lease.token, ttl_seconds)
        if result != 1:
            raise LeaseNotOwned("lease is not owned by caller")
        return Lease(lease.key, lease.owner, lease.token, current + timedelta(seconds=ttl_seconds))

    def release(self, lease: Lease) -> None:
        result = self._client.eval(_RELEASE, 1, lease.key, lease.token)
        if result != 1:
            raise LeaseNotOwned("lease is not owned by caller")
