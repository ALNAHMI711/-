from datetime import datetime, timezone

import pytest

from app.compute_nodes import ComputeNode, ComputeNodeManager, NodeKind, NodeState
from app.control_plane import ControlPlane, DispatchError
from app.redis_coordination import InMemoryLeaseCoordinator, LeaseConflict


NOW = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)


def make_plane(lease_coordinator=None) -> ControlPlane:
    nodes = ComputeNodeManager(
        [ComputeNode("worker-1", "Worker 1", NodeKind.FREE_TIER, state=NodeState.ONLINE)]
    )
    return ControlPlane(nodes=nodes, lease_coordinator=lease_coordinator)


def prepare_job(plane: ControlPlane) -> None:
    from app.scheduler import ScheduledJob

    plane.scheduler.add(ScheduledJob("s1", "render", NOW))
    plane.materialize_due(NOW)


def test_due_schedule_materializes_and_dispatches_command() -> None:
    plane = make_plane()
    prepare_job(plane)
    lease = plane.dispatch("s1", now=NOW)

    assert lease.worker_id == "worker-1"
    assert lease.command.job_id == "s1"
    assert lease.command.job_type == "render"
    assert lease.command.worker_id == "worker-1"
    assert lease.command.expires_at > NOW
    assert plane.queue.get("s1").worker_id == "worker-1"
    assert plane.nodes.get("worker-1").current_jobs == 1


def test_distributed_lease_is_acquired_and_released() -> None:
    coordinator = InMemoryLeaseCoordinator()
    plane = make_plane(coordinator)
    prepare_job(plane)
    plane.dispatch("s1", now=NOW)

    assert "job:s1" in coordinator._leases
    plane.succeed("s1", "worker-1")
    assert "job:s1" not in coordinator._leases


def test_distributed_lease_conflict_blocks_dispatch_without_consuming_worker() -> None:
    coordinator = InMemoryLeaseCoordinator()
    coordinator.acquire_job("job:s1", "other-worker", 300, now=NOW)
    plane = make_plane(coordinator)
    prepare_job(plane)

    with pytest.raises(LeaseConflict, match="already held"):
        plane.dispatch("s1", now=NOW)
    assert plane.queue.get("s1").state.value == "failed"
    assert plane.nodes.get("worker-1").current_jobs == 0


def test_distributed_lease_renews_with_queue_lease() -> None:
    coordinator = InMemoryLeaseCoordinator()
    plane = make_plane(coordinator)
    prepare_job(plane)
    plane.dispatch("s1", lease_seconds=30, now=NOW)
    renewed = plane.renew("s1", "worker-1", lease_seconds=120, now=NOW)

    assert renewed is not None
    assert renewed.expires_at == NOW.replace(second=0) + __import__("datetime").timedelta(seconds=120)
    assert plane.queue.get("s1").lease_until == renewed.expires_at


def test_failed_job_releases_distributed_lease_for_retry() -> None:
    coordinator = InMemoryLeaseCoordinator()
    plane = make_plane(coordinator)
    prepare_job(plane)
    plane.dispatch("s1", now=NOW)
    job = plane.fail("s1", "temporary worker error", retry=True)

    assert job.state.value == "queued"
    assert "job:s1" not in coordinator._leases
    plane.dispatch("s1", now=NOW)
    assert "job:s1" in coordinator._leases


def test_wrong_worker_cannot_complete_or_cancel_job() -> None:
    plane = make_plane()
    prepare_job(plane)
    plane.dispatch("s1", now=NOW)

    with pytest.raises(DispatchError, match="does not own"):
        plane.succeed("s1", "worker-2")
    with pytest.raises(DispatchError, match="does not own"):
        plane.fail("s1", "worker-2", "spoofed")
    with pytest.raises(DispatchError, match="does not own"):
        plane.cancel("s1", "worker-2")


def test_success_releases_worker_capacity_and_finishes_command() -> None:
    plane = make_plane()
    prepare_job(plane)
    lease = plane.dispatch("s1", now=NOW)
    job = plane.succeed("s1", "worker-1")

    assert job.state.value == "succeeded"
    assert plane.nodes.get("worker-1").current_jobs == 0
    result = plane.command_ledger.finish(lease.command.command_id, "worker-1", True)
    assert result.status.value == "succeeded"


def test_failed_job_can_retry_and_release_worker() -> None:
    plane = make_plane()
    prepare_job(plane)
    lease = plane.dispatch("s1", now=NOW)
    job = plane.fail("s1", "worker-1", "temporary worker error", retry=True)

    assert job.state.value == "queued"
    assert job.worker_id is None
    assert plane.nodes.get("worker-1").current_jobs == 0
    result = plane.command_ledger.finish(lease.command.command_id, "worker-1", False, "temporary worker error")
    assert result.status.value == "failed"


def test_no_worker_leaves_job_queued() -> None:
    plane = ControlPlane()
    prepare_job(plane)

    with pytest.raises(DispatchError, match="no available node"):
        plane.dispatch("s1", now=NOW)
    assert plane.queue.get("s1").state.value == "queued"


def test_capability_filter_blocks_incompatible_worker() -> None:
    plane = make_plane()
    prepare_job(plane)

    with pytest.raises(DispatchError, match="no available node"):
        plane.dispatch("s1", required_capabilities=frozenset({"ffmpeg"}), now=NOW)
