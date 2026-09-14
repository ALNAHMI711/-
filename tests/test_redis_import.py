def test_redis_dependency_imports():
    import redis
    assert redis.__version__
