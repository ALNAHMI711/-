def test_redis_health_boundary_is_separate():
    from app.redis_client import RedisLeaseCommands
    commands = RedisLeaseCommands()
    assert commands.acquire
    assert commands.renew
    assert commands.release
