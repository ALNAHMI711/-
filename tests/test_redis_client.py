import pytest

from app.redis_client import RedisLeaseCommands, validate_redis_url


def test_validate_redis_urls():
    assert validate_redis_url("redis://localhost:6379/0").startswith("redis://")
    assert validate_redis_url("rediss://cache.example/0").startswith("rediss://")


def test_reject_non_redis_urls():
    with pytest.raises(ValueError):
        validate_redis_url("postgresql://db")


def test_commands_are_explicit():
    commands = RedisLeaseCommands()
    assert "NX" in commands.acquire
    assert "atomic" in commands.release
