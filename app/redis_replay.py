"""Atomic Redis replay protection for authenticated worker messages."""

import redis

_CLAIM = """
if redis.call('EXISTS', KEYS[1]) == 1 then
  return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 1
"""


class RedisReplayGuard:
    """Atomically claim message IDs for a worker within their replay window."""

    def __init__(self, client: redis.Redis, prefix: str = "mashahid:replay:") -> None:
        if not prefix:
            raise ValueError("prefix is required")
        self._client = client
        self._prefix = prefix

    def claim(self, message_id: str, worker_id: str, ttl_seconds: int) -> bool:
        if not message_id.strip() or not worker_id.strip() or ttl_seconds <= 0:
            raise ValueError("valid message_id, worker_id and ttl_seconds are required")
        key = f"{self._prefix}{worker_id}:{message_id}"
        return bool(self._client.eval(_CLAIM, 1, key, "1", ttl_seconds))
