"""Redis coordination primitives for distributed worker leases.

Redis is used only for short-lived coordination. PostgreSQL remains the durable
source of truth for job history and state.
"""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Lease:
    key: str
    owner: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.owner.strip():
            raise ValueError("lease key and owner are required")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")

    def expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return current >= self.expires_at


class LeaseNotOwned(RuntimeError):
    """Raised when a worker attempts to renew or release another worker's lease."""


class InMemoryLeaseCoordinator:
    """Deterministic coordination implementation used by tests/development."""

    def __init__(self) -> None:
        self._leases: dict[str, Lease] = {}

    def acquire(self, key: str, owner: str, ttl_seconds: int, now: datetime | None = None) -> Lease:
        if not key.strip() or not owner.strip():
            raise ValueError("lease key and owner are required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        existing = self._leases.get(key)
        if existing is not None and not existing.expired(current):
            raise LeaseNotOwned("lease is already held")
        lease = Lease(key, owner, current + __import__("datetime").timedelta(seconds=ttl_seconds))
        self._leases[key] = lease
        return lease

    def renew(self, lease: Lease, ttl_seconds: int, now: datetime | None = None) -> Lease:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        current = now or datetime.now(timezone.utc)
        stored = self._leases.get(lease.key)
        if stored != lease or stored.expired(current):
            raise LeaseNotOwned("lease is not active")
        renewed = Lease(lease.key, lease.owner, current + __import__("datetime").timedelta(seconds=ttl_seconds))
        self._leases[lease.key] = renewed
        return renewed

    def release(self, lease: Lease) -> None:
        stored = self._leases.get(lease.key)
        if stored != lease:
            raise LeaseNotOwned("lease is not owned by caller")
        self._leases.pop(lease.key, None)
