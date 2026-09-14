"""Replay protection contracts for authenticated worker messages."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Protocol


class ReplayGuard(Protocol):
    """Atomically claim a message ID for a worker until its replay window ends."""

    def claim(self, message_id: str, worker_id: str, ttl_seconds: int) -> bool:
        ...


@dataclass
class InMemoryReplayGuard:
    """Small deterministic implementation for tests and local development."""

    _claims: dict[tuple[str, str], datetime] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def claim(self, message_id: str, worker_id: str, ttl_seconds: int) -> bool:
        if not message_id.strip() or not worker_id.strip():
            raise ValueError("message_id and worker_id are required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = datetime.now(timezone.utc)
        key = (worker_id, message_id)
        with self._lock:
            expires_at = self._claims.get(key)
            if expires_at is not None and expires_at > now:
                return False
            self._claims[key] = now + timedelta(seconds=ttl_seconds)
            return True
