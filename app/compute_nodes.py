"""Compute-node registry and safe job routing primitives for Mashahid.

The control plane keeps node metadata only. Credentials for private workers are
represented by opaque references and are never stored in node objects.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable


class NodeKind(str, Enum):
    FREE_TIER = "free_tier"
    PRIVATE = "private"


class NodeState(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DRAINING = "draining"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ResourceSnapshot:
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    storage_percent: float = 0.0

    def __post_init__(self) -> None:
        for value in (self.cpu_percent, self.memory_percent, self.storage_percent):
            if not 0.0 <= value <= 100.0:
                raise ValueError("resource percentages must be between 0 and 100")


@dataclass
class ComputeNode:
    node_id: str
    name: str
    kind: NodeKind
    state: NodeState = NodeState.UNKNOWN
    capabilities: frozenset[str] = field(default_factory=frozenset)
    max_concurrency: int = 1
    current_jobs: int = 0
    usage_limit_remaining: int | None = None
    last_heartbeat: datetime | None = None
    resources: ResourceSnapshot = field(default_factory=ResourceSnapshot)
    credential_ref: str | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.name.strip():
            raise ValueError("node_id and name are required")
        if self.max_concurrency < 1 or self.current_jobs < 0:
            raise ValueError("invalid node capacity")
        if self.current_jobs > self.max_concurrency:
            raise ValueError("current_jobs cannot exceed max_concurrency")
        if self.usage_limit_remaining is not None and self.usage_limit_remaining < 0:
            raise ValueError("usage_limit_remaining cannot be negative")

    @property
    def available(self) -> bool:
        return (
            self.state == NodeState.ONLINE
            and self.current_jobs < self.max_concurrency
            and (self.usage_limit_remaining is None or self.usage_limit_remaining > 0)
        )

    def heartbeat(self, resources: ResourceSnapshot, now: datetime | None = None) -> None:
        self.state = NodeState.ONLINE
        self.resources = resources
        self.last_heartbeat = now or datetime.now(timezone.utc)
        self.last_error = None


@dataclass(frozen=True)
class JobRequest:
    job_id: str
    required_capabilities: frozenset[str] = frozenset()


class NoAvailableNode(RuntimeError):
    """Raised when no healthy worker can accept the job."""


class ComputeNodeManager:
    """In-memory manager used as the domain contract for a persistent service."""

    def __init__(self, nodes: Iterable[ComputeNode] = ()) -> None:
        self._nodes: dict[str, ComputeNode] = {}
        for node in nodes:
            self.register(node)

    def register(self, node: ComputeNode) -> None:
        if node.node_id in self._nodes:
            raise ValueError(f"node already registered: {node.node_id}")
        self._nodes[node.node_id] = node

    def get(self, node_id: str) -> ComputeNode:
        try:
            return self._nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown compute node: {node_id}") from exc

    def list_nodes(self) -> tuple[ComputeNode, ...]:
        return tuple(self._nodes[key] for key in sorted(self._nodes))

    def route(self, request: JobRequest) -> ComputeNode:
        candidates = [
            node for node in self._nodes.values()
            if node.available and request.required_capabilities <= node.capabilities
        ]
        if not candidates:
            raise NoAvailableNode(f"no available node for job {request.job_id}")
        # Prefer the least-loaded capable node; stable node_id tie-breaker.
        selected = min(candidates, key=lambda n: (n.current_jobs / n.max_concurrency, n.node_id))
        selected.current_jobs += 1
        if selected.usage_limit_remaining is not None:
            selected.usage_limit_remaining -= 1
        return selected

    def release(self, node_id: str) -> None:
        node = self.get(node_id)
        if node.current_jobs <= 0:
            raise ValueError("node has no running jobs")
        node.current_jobs -= 1

    def mark_error(self, node_id: str, message: str) -> None:
        node = self.get(node_id)
        node.state = NodeState.ERROR
        node.last_error = message[:500]

    def mark_draining(self, node_id: str) -> None:
        self.get(node_id).state = NodeState.DRAINING

    def failover_candidates(self, request: JobRequest, exclude_node_id: str) -> tuple[ComputeNode, ...]:
        return tuple(
            node for node in self.list_nodes()
            if node.node_id != exclude_node_id
            and node.available
            and request.required_capabilities <= node.capabilities
        )
