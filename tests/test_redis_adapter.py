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

    def eval(self, script, numkeys, key, token, *args):
        if self.values.get(key) != token:
            return 0
        if "DEL" in script:
            del self.values[key]
        return 1


def test_redis_adapter_uses_opaque_token_for_owner_checked_operations():
    client = FakeRedis()
    adapter = RedisLeaseCoordinator(client)
    now = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
    lease = adapter.acquire("job:j1", "worker-1", 30, now=now)
    assert lease.owner == "worker-1"
    assert lease.token
    assert lease.token != lease.owner
    assert client.values["job:j1"] == lease.token
    renewed = adapter.renew(lease, 60, now=now)
    assert renewed.token == lease.token
    adapter.release(renewed)
    assert client.values == {}


def test_redis_adapter_rejects_competing_owner():
    client = FakeRedis()
    adapter = RedisLeaseCoordinator(client)
    now = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
    adapter.acquire("job:j1", "worker-1", 30, now=now)
    with pytest.raises(LeaseNotOwned, match="already held"):
        adapter.acquire("job:j1", "worker-2", 30, now=now)


def test_redis_adapter_rejects_forged_token():
    client = FakeRedis()
    adapter = RedisLeaseCoordinator(client)
    now = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
    lease = adapter.acquire("job:j1", "worker-1", 30, now=now)
    forged = type(lease)(lease.key, lease.owner, "forged-token", lease.expires_at)
    with pytest.raises(LeaseNotOwned):
        adapter.renew(forged, 30, now=now)
    with pytest.raises(LeaseNotOwned):
        adapter.release(forged)
