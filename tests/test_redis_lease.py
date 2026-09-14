from datetime import timezone

import pytest

from app.redis_coordination import Lease, LeaseConflict, LeaseNotOwned
from app.redis_lease import RedisLeaseCoordinator


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, token, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = token
        return True

    def eval(self, script, keys, key, token, ttl=None):
        if self.values.get(key) != token:
            return 0
        if "del" in script:
            del self.values[key]
            return 1
        return 1


def coordinator():
    value = RedisLeaseCoordinator.__new__(RedisLeaseCoordinator)
    value._client = FakeRedis()
    value._prefix = "test:"
    return value


def test_redis_adapter_acquire_and_release():
    adapter = coordinator()
    lease = adapter.acquire("job-1", "worker-1", 30)
    assert lease.owner == "worker-1"
    assert lease.expires_at.tzinfo == timezone.utc
    adapter.release(lease)


def test_redis_adapter_conflict_and_wrong_token():
    adapter = coordinator()
    lease = adapter.acquire("job-1", "worker-1", 30)
    with pytest.raises(LeaseConflict):
        adapter.acquire("job-1", "worker-2", 30)
    forged = Lease(lease.key, lease.owner, "wrong", lease.expires_at)
    with pytest.raises(LeaseNotOwned):
        adapter.renew(forged, 30)
    with pytest.raises(LeaseNotOwned):
        adapter.release(forged)
