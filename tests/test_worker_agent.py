from datetime import datetime, timezone

import pytest

from app.worker_agent import AgentState, WorkerAgent, WorkerHeartbeat


def test_heartbeat_marks_worker_online_and_clears_error() -> None:
    worker = WorkerAgent(node_id="node-1", name="Free Worker")
    worker.mark_error("temporary failure")

    heartbeat = WorkerHeartbeat(
        node_id="node-1",
        sent_at=datetime(2026, 9, 14, 20, 0, tzinfo=timezone.utc),
        cpu_percent=12.5,
        memory_percent=30.0,
        storage_percent=40.0,
    )
    worker.receive_heartbeat(heartbeat)

    assert worker.state is AgentState.ONLINE
    assert worker.last_error is None
    assert worker.controllable


def test_heartbeat_rejects_wrong_node() -> None:
    worker = WorkerAgent(node_id="node-1", name="Private Worker")
    heartbeat = WorkerHeartbeat(
        node_id="node-2",
        sent_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ValueError, match="node mismatch"):
        worker.receive_heartbeat(heartbeat)


def test_heartbeat_requires_aware_timestamp_and_valid_resources() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        WorkerHeartbeat(node_id="node-1", sent_at=datetime(2026, 1, 1))

    with pytest.raises(ValueError, match="between 0 and 100"):
        WorkerHeartbeat(
            node_id="node-1",
            sent_at=datetime.now(timezone.utc),
            cpu_percent=101,
        )


def test_error_is_bounded_and_drain_is_controllable() -> None:
    worker = WorkerAgent(node_id="node-1", name="Private Worker")
    worker.mark_error("x" * 1000)
    assert worker.state is AgentState.ERROR
    assert len(worker.last_error or "") == 500

    worker.drain()
    assert worker.state is AgentState.DRAINING
    assert worker.controllable
