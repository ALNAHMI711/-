"""Lease contracts for distributed worker coordination.

PostgreSQL remains the durable source of truth. Redis is only a short-lived
coordination mechanism and must never contain platform credentials or tokens.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Lease:
    key: str
    owner: str
    token: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.owner.strip() or not self.token.strip():
            raise ValueError("lease key, owner and token are required")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")

    def expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return current >= self.expires_at


class LeaseConflict(RuntimeError):
    """Raised when a non-expired lease is already held."""


class LeaseNotOwned(RuntimeError):
    """Raised when the supplied ownership token does not match the lease."""


class InMemoryLeaseCoordinator:
    """Deterministic lease implementation used by tests/development only."""

    def __init__(self) -> None:
        self._leases: dict[str, Lease] = {}

    def acquire(self, key: str, owner: str, token: str, ttl_seconds: int,
                now: datetime | None = None) -> Lease:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        existing = self._leases.get(key)
        if existing is not None and not existing.expired(current):
            raise LeaseConflict("lease is already held")
        lease = Lease(key, owner, token, current + timedelta(seconds=ttl_seconds))
        self._leases[key] = lease
        return lease

    def renew(self, lease: Lease, ttl_seconds: int,
              now: datetime | None = None) -> Lease:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        current = now or datetime.now(timezone.utc)
        stored = self._leases.get(lease.key)
        if stored is None or stored.token != lease.token or stored.owner != lease.owner:
            raise LeaseNotOwned("lease ownership token is invalid")
        if stored.expired(current):
            raise LeaseNotOwned("lease is expired")
        renewed = Lease(lease.key, lease.owner, lease.token,
                        current + timedelta(seconds=ttl_seconds))
        self._leases[lease.key] = renewed
        return renewed

    def release(self, lease: Lease) -> None:
        stored = self._leases.get(lease.key)
        if stored is None or stored.token != lease.token or stored.owner != lease.owner:
            raise LeaseNotOwned("lease ownership token is invalid")
        self._leases.pop(lease.key, None)
