"""Integration facade for selecting Redis coordination implementations."""

from .redis_adapter import RedisLeaseCoordinator as ProductionRedisLeaseCoordinator
from .redis_coordination import InMemoryLeaseCoordinator

__all__ = ["InMemoryLeaseCoordinator", "ProductionRedisLeaseCoordinator"]
