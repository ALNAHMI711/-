"""Secure outbound worker-agent primitives for Mashahid.

Workers connect outward to the control plane. The control plane stores only
opaque enrollment references and health metadata; worker secrets never belong
in domain objects or logs.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class AgentState(str, Enum):
    UNENROLLED = "unenrolled"
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
    DRAINING = "draining"


@dataclass(frozen=True)
class WorkerHeartbeat:
    node_id: str
    sent_at: datetime
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    storage_percent: float = 0.0

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ValueError("node_id is required")
        if self.sent_at.tzinfo is None:
            raise ValueError("sent_at must be timezone-aware")
        for name, value in (("cpu_percent", self.cpu_percent), ("memory_percent", self.memory_percent), ("storage_percent", self.storage_percent)):
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} must be between 0 and 100")


@dataclass
class WorkerAgent:
    node_id: str
    name: str
    state: AgentState = AgentState.UNENROLLED
    enrollment_ref: str | None = None
    last_heartbeat: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.name.strip():
            raise ValueError("node_id and name are required")

    def receive_heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        if heartbeat.node_id != self.node_id:
            raise ValueError("heartbeat node mismatch")
        self.last_heartbeat = heartbeat.sent_at.astimezone(timezone.utc)
        self.state = AgentState.ONLINE
        self.last_error = None

    def mark_error(self, message: str) -> None:
        self.state = AgentState.ERROR
        self.last_error = message.strip()[:500] or "worker error"

    def drain(self) -> None:
        self.state = AgentState.DRAINING

    @property
    def controllable(self) -> bool:
        return self.state in {AgentState.ONLINE, AgentState.DRAINING}
