from datetime import datetime, timezone

import pytest

from app.redis_coordination import InMemoryLeaseCoordinator, Lease, LeaseNotOwned

NOW = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)


def test_acquire_renew_and_release():
    coordinator = InMemoryLeaseCoordinator()
    lease = coordinator.acquire("job:j1", "worker-1", 30, now=NOW)
    renewed = coordinator.renew(lease, 60, now=NOW)
    assert renewed.expires_at > lease.expires_at
    coordinator.release(renewed)


def test_active_lease_blocks_other_owner():
    coordinator = InMemoryLeaseCoordinator()
    coordinator.acquire("job:j1", "worker-1", 30, now=NOW)
    with pytest.raises(LeaseNotOwned, match="already held"):
        coordinator.acquire("job:j1", "worker-2", 30, now=NOW)


def test_expired_lease_can_be_reclaimed():
    coordinator = InMemoryLeaseCoordinator()
    lease = coordinator.acquire("job:j1", "worker-1", 1, now=NOW)
    replacement = coordinator.acquire("job:j1", "worker-2", 30, now=lease.expires_at)
    assert replacement.owner == "worker-2"


def test_wrong_owner_cannot_renew_or_release():
    coordinator = InMemoryLeaseCoordinator()
    lease = coordinator.acquire("job:j1", "worker-1", 30, now=NOW)
    forged = Lease(lease.key, "worker-2", lease.expires_at)
    with pytest.raises(LeaseNotOwned):
        coordinator.renew(forged, 30, now=NOW)
    with pytest.raises(LeaseNotOwned):
        coordinator.release(forged)
