from datetime import datetime, timezone

import pytest

from app.oauth_session import OAuthState
from app.redis_oauth_state import RedisOAuthStateStore


class FakeRedis:
    def __init__(self):
        self.data = {}

    def eval(self, script, numkeys, key, *args):
        if "NX" in script:
            if key in self.data:
                return self.data[key]
            self.data[key] = args[0]
            return self.data[key]
        if key not in self.data:
            return 0
        if self.data[key] != args[0]:
            return 0
        del self.data[key]
        return 1

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


def test_redis_state_is_single_use_and_project_bound():
    store = RedisOAuthStateStore(FakeRedis(), ttl_seconds=60)
    state = store.create("youtube", now=100.0, user_id="u1", project_id="p1")
    assert store.get(state.value, now=100.0) == state
    assert store.consume(state, state.value, now=101.0) is True
    assert store.consume(state, state.value, now=101.0) is False


def test_redis_state_rejects_expired_state():
    store = RedisOAuthStateStore(FakeRedis(), ttl_seconds=60)
    state = store.create("youtube", now=100.0, user_id="u1", project_id="p1")
    assert store.get(state.value, now=161.0) is None
    assert store.consume(state, state.value, now=161.0) is False


def test_redis_state_requires_user_and_project_together():
    store = RedisOAuthStateStore(FakeRedis())
    with pytest.raises(ValueError):
        store.create("youtube", user_id="u1")
