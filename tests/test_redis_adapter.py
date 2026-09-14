from datetime import datetime, timezone

import pytest

from app.redis_adapter import RedisLeaseCoordinator
from app.redis_coordination import LeaseNotOwned


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, script, numkeys, key, owner, *args):
        if self.values.get(key) != owner:
            return 0
        if "DEL" in script:
            del self.values[key]
        return 1


def test_redis_adapter_uses_owner_checked_operations():
    client = FakeRedis()
    adapter = RedisLeaseCoordinator(client)
    now = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
    lease = adapter.acquire("job:j1", "worker-1", 30, now=now)
    renewed = adapter.renew(lease, 60, now=now)
    assert renewed.owner == "worker-1"
    adapter.release(renewed)
    assert client.values == {}


def test_redis_adapter_rejects_competing_owner():
    client = FakeRedis()
    adapter = RedisLeaseCoordinator(client)
    now = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
    adapter.acquire("job:j1", "worker-1", 30, now=now)
    with pytest.raises(LeaseNotOwned):
        adapter.acquire("job:j1", "worker-2", 30, now=now)
