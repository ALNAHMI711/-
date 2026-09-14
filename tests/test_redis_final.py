def test_redis_boundary_is_explicit():
    from app.redis_integration import ProductionRedisLeaseCoordinator
    assert ProductionRedisLeaseCoordinator
