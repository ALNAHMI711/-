from datetime import datetime, timezone

from app.redis_adapter_fixed import RedisLeaseCoordinator


class FakeRedis:
    def __init__(self): self.values = {}
    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values: return False
        self.values[key] = value
        return True
    def eval(self, script, numkeys, key, owner, *args):
        if self.values.get(key) != owner: return 0
        if "DEL" in script: del self.values[key]
        return 1


def test_clean_adapter_lifecycle():
    client = FakeRedis()
    adapter = RedisLeaseCoordinator(client)
    now = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)
    lease = adapter.acquire("job:j1", "worker-1", 30, now=now)
    lease = adapter.renew(lease, 60, now=now)
    adapter.release(lease)
    assert client.values == {}
