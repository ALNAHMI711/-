"""Production Redis implementation of short-lived worker leases."""

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

import redis

from .redis_coordination import Lease, LeaseConflict, LeaseNotOwned

_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


class RedisLeaseCoordinator:
    """Atomic Redis-backed lease store; Redis is coordination only."""

    def __init__(self, url: str, prefix: str = "mashahid:lease:") -> None:
        value = url.strip()
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("Redis URL must use redis:// or rediss://")
        if not prefix.strip():
            raise ValueError("prefix is required")
        self._client = redis.Redis.from_url(value, decode_responses=True)
        self._prefix = prefix

    def _key(self, key: str) -> str:
        if not key.strip():
            raise ValueError("lease key is required")
        return f"{self._prefix}{key}"

    def acquire(self, key: str, owner: str, ttl_seconds: int) -> Lease:
        if not owner.strip() or ttl_seconds <= 0:
            raise ValueError("owner and positive ttl_seconds are required")
        token = token_urlsafe(32)
        if not self._client.set(self._key(key), token, nx=True, ex=ttl_seconds):
            raise LeaseConflict("lease is already held")
        return Lease(key, owner, token, datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))

    def renew(self, lease: Lease, ttl_seconds: int) -> Lease:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        result = self._client.eval(_RENEW, 1, self._key(lease.key), lease.token, ttl_seconds)
        if result != 1:
            raise LeaseNotOwned("lease ownership token is invalid or expired")
        return Lease(lease.key, lease.owner, lease.token,
                     datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))

    def release(self, lease: Lease) -> None:
        result = self._client.eval(_RELEASE, 1, self._key(lease.key), lease.token)
        if result != 1:
            raise LeaseNotOwned("lease ownership token is invalid or expired")
