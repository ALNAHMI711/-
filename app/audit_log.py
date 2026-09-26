"""Safe audit events for publishing and control-plane actions."""
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    actor_id: str
    action: str
    project_id: str
    target_id: str
    outcome: str
    created_at: datetime


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        if not event.event_id.strip() or not event.action.strip():
            raise ValueError("event_id and action are required")
        self._events.append(event)

    def list_for_project(self, project_id: str) -> tuple[AuditEvent, ...]:
        return tuple(e for e in self._events if e.project_id == project_id)

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)
