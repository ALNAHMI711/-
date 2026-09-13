from datetime import datetime, timezone

import pytest

from app.compute_nodes import (
    ComputeNode,
    ComputeNodeManager,
    JobRequest,
    NodeKind,
    NodeState,
    NoAvailableNode,
    ResourceSnapshot,
)


def node(node_id: str, kind: NodeKind = NodeKind.FREE_TIER, **kwargs) -> ComputeNode:
    return ComputeNode(node_id=node_id, name=node_id, kind=kind, **kwargs)


def test_routes_to_least_loaded_capable_online_node() -> None:
    manager = ComputeNodeManager(
        [
            node("busy", capabilities=frozenset({"video"}), current_jobs=1, max_concurrency=2),
            node("free", capabilities=frozenset({"video"}), max_concurrency=2),
        ]
    )
    selected = manager.route(JobRequest("job-1", frozenset({"video"})))
    assert selected.node_id == "free"
    assert selected.current_jobs == 1


def test_capacity_and_usage_limits_are_enforced() -> None:
    manager = ComputeNodeManager([
        node("full", current_jobs=1, max_concurrency=1),
        node("quota", usage_limit_remaining=0),
    ])
    with pytest.raises(NoAvailableNode):
        manager.route(JobRequest("job-2"))


def test_private_node_can_be_used_without_storing_raw_secret() -> None:
    private = node("private-1", NodeKind.PRIVATE, credential_ref="secret-ref-123")
    manager = ComputeNodeManager([private])
    selected = manager.route(JobRequest("job-3"))
    assert selected.kind == NodeKind.PRIVATE
    assert selected.credential_ref == "secret-ref-123"


def test_heartbeat_restores_online_state_and_updates_resources() -> None:
    n = node("worker", state=NodeState.ERROR, last_error="network")
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    n.heartbeat(ResourceSnapshot(cpu_percent=12, memory_percent=30, storage_percent=40), stamp)
    assert n.state == NodeState.ONLINE
    assert n.last_error is None
    assert n.last_heartbeat == stamp
    assert n.resources.memory_percent == 30


def test_failover_excludes_failed_node() -> None:
    manager = ComputeNodeManager([node("a"), node("b")])
    manager.mark_error("a", "worker failed")
    candidates = manager.failover_candidates(JobRequest("job-4"), "a")
    assert [n.node_id for n in candidates] == ["b"]


def test_release_cannot_make_job_count_negative() -> None:
    manager = ComputeNodeManager([node("a")])
    with pytest.raises(ValueError):
        manager.release("a")
