"""Small production-facing Redis lease adapter boundary.

The adapter is intentionally dependency-free until the Redis deployment is
configured. It documents the exact operations required by the coordinator.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RedisLeaseCommands:
    """Commands a Redis adapter must implement atomically."""

    acquire: str = "SET lease_key owner NX EX ttl"
    release: str = "owner-checked atomic delete"
    renew: str = "owner-checked atomic expiry update"


def validate_redis_url(url: str) -> str:
    """Accept only Redis connection URLs; credentials remain outside domain objects."""
    value = url.strip()
    if not value.startswith(("redis://", "rediss://")):
        raise ValueError("Redis URL must use redis:// or rediss://")
    return value
