"""Clean Redis lease adapter reference used until the main adapter is revised."""

from datetime import datetime, timedelta, timezone

import redis

from .redis_coordination import Lease, LeaseNotOwned

_RELEASE = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"
_RENEW = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('EXPIRE', KEYS[1], ARGV[2]) end return 0"


class RedisLeaseCoordinator:
    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def acquire(self, key: str, owner: str, ttl_seconds: int, now: datetime | None = None) -> Lease:
        if not key.strip() or not owner.strip() or ttl_seconds <= 0:
            raise ValueError("valid key, owner and ttl_seconds are required")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if not self._client.set(key, owner, nx=True, ex=ttl_seconds):
            raise LeaseNotOwned("lease is already held")
        return Lease(key, owner, current + timedelta(seconds=ttl_seconds))

    def renew(self, lease: Lease, ttl_seconds: int, now: datetime | None = None) -> Lease:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if self._client.eval(_RENEW, 1, lease.key, lease.owner, ttl_seconds) != 1:
            raise LeaseNotOwned("lease is not owned by caller")
        return Lease(lease.key, lease.owner, current + timedelta(seconds=ttl_seconds))

    def release(self, lease: Lease) -> None:
        if self._client.eval(_RELEASE, 1, lease.key, lease.owner) != 1:
            raise LeaseNotOwned("lease is not owned by caller")
