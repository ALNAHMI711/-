import os

import pytest

from app.replay_protection import InMemoryReplayGuard
from app.redis_replay import RedisReplayGuard
from app.worker_transport import TransportRejected, validate_envelope

from .test_worker_transport import SECRET, NOW, envelope


def test_in_memory_guard_rejects_duplicate_message():
    guard = InMemoryReplayGuard()
    assert guard.claim("m1", "w1", 30)
    assert not guard.claim("m1", "w1", 30)
    assert guard.claim("m1", "w2", 30)


def test_replay_is_checked_only_after_authentication():
    guard = InMemoryReplayGuard()
    bad = envelope(secret="wrong")
    with pytest.raises(TransportRejected, match="authentication failed"):
        validate_envelope(bad, "w1", SECRET, NOW, replay_guard=guard)
    assert guard.claim("m1", "w1", 30)


@pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="REDIS_URL is required for Redis integration")
def test_redis_replay_guard_is_atomic_across_instances():
    import redis

    client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    client.flushdb()
    first = RedisReplayGuard(client)
    second = RedisReplayGuard(client)
    assert first.claim("integration-message", "w1", 30)
    assert not second.claim("integration-message", "w1", 30)
    assert second.claim("integration-message", "w2", 30)
    client.delete("mashahid:replay:w1:integration-message", "mashahid:replay:w2:integration-message")
