"""Simple scheduler domain contract for due job creation."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ScheduledJob:
    schedule_id: str
    job_type: str
    run_at: datetime
    enabled: bool = True
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.schedule_id.strip() or not self.job_type.strip():
            raise ValueError("schedule_id and job_type are required")
        if self.run_at.tzinfo is None:
            raise ValueError("run_at must be timezone-aware")


class Scheduler:
    """In-memory scheduler; persistent scheduling belongs to the production DB."""

    def __init__(self) -> None:
        self._items: dict[str, ScheduledJob] = {}
        self._emitted: set[str] = set()

    def add(self, item: ScheduledJob) -> None:
        if item.schedule_id in self._items:
            raise ValueError("schedule already exists")
        self._items[item.schedule_id] = item

    def remove(self, schedule_id: str) -> None:
        self._items.pop(schedule_id, None)
        self._emitted.discard(schedule_id)

    def pause(self, schedule_id: str) -> None:
        item = self._items[schedule_id]
        self._items[schedule_id] = ScheduledJob(item.schedule_id, item.job_type, item.run_at, False, item.idempotency_key)

    def resume(self, schedule_id: str) -> None:
        item = self._items[schedule_id]
        self._items[schedule_id] = ScheduledJob(item.schedule_id, item.job_type, item.run_at, True, item.idempotency_key)

    def due(self, now: datetime | None = None) -> tuple[ScheduledJob, ...]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        current = current.astimezone(timezone.utc)
        due_items = []
        for item in self._items.values():
            if item.enabled and item.schedule_id not in self._emitted and item.run_at.astimezone(timezone.utc) <= current:
                due_items.append(item)
                self._emitted.add(item.schedule_id)
        return tuple(sorted(due_items, key=lambda value: (value.run_at, value.schedule_id)))
