def test_redis_integration_exports():
    from app.redis_integration import InMemoryLeaseCoordinator, ProductionRedisLeaseCoordinator
    assert InMemoryLeaseCoordinator is not None
    assert ProductionRedisLeaseCoordinator is not None
