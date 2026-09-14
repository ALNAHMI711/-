from datetime import datetime, timedelta, timezone

import pytest

from app.compute_nodes import ComputeNode, ComputeNodeManager, NodeKind, NodeState
from app.control_plane import ControlPlane, DispatchError


NOW = datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc)


def make_plane() -> ControlPlane:
    nodes = ComputeNodeManager(
        [ComputeNode("worker-1", "Worker 1", NodeKind.FREE_TIER, state=NodeState.ONLINE)]
    )
    return ControlPlane(nodes=nodes)


def test_due_schedule_materializes_and_dispatches() -> None:
    plane = make_plane()
    from app.scheduler import ScheduledJob

    plane.scheduler.add(ScheduledJob("s1", "render", NOW))
    jobs = plane.materialize_due(NOW)
    assert [job.job_id for job in jobs] == ["s1"]

    lease = plane.dispatch("s1", now=NOW)
    assert lease.worker_id == "worker-1"
    assert plane.queue.get("s1").worker_id == "worker-1"
    assert plane.nodes.get("worker-1").current_jobs == 1


def test_wrong_worker_cannot_complete_job() -> None:
    plane = make_plane()
    from app.scheduler import ScheduledJob

    plane.scheduler.add(ScheduledJob("s1", "render", NOW))
    plane.materialize_due(NOW)
    plane.dispatch("s1", now=NOW)

    with pytest.raises(DispatchError, match="does not own"):
        plane.complete_with_owner_check("s1", "worker-2")


def test_success_releases_worker_capacity() -> None:
    plane = make_plane()
    from app.scheduler import ScheduledJob

    plane.scheduler.add(ScheduledJob("s1", "render", NOW))
    plane.materialize_due(NOW)
    plane.dispatch("s1", now=NOW)
    job = plane.complete_with_owner_check("s1", "worker-1")

    assert job.state.value == "succeeded"
    assert plane.nodes.get("worker-1").current_jobs == 0


def test_failed_job_can_retry_and_release_worker() -> None:
    plane = make_plane()
    from app.scheduler import ScheduledJob

    plane.scheduler.add(ScheduledJob("s1", "render", NOW))
    plane.materialize_due(NOW)
    plane.dispatch("s1", now=NOW)
    job = plane.fail_with_owner_check("s1", "worker-1", "temporary worker error", retry=True)

    assert job.state.value == "queued"
    assert job.worker_id is None
    assert plane.nodes.get("worker-1").current_jobs == 0


def test_no_worker_leaves_job_queued() -> None:
    plane = ControlPlane()
    from app.scheduler import ScheduledJob

    plane.scheduler.add(ScheduledJob("s1", "render", NOW))
    plane.materialize_due(NOW)

    with pytest.raises(DispatchError, match="no available node"):
        plane.dispatch("s1", now=NOW)
    assert plane.queue.get("s1").state.value == "queued"


def test_capability_filter_blocks_incompatible_worker() -> None:
    plane = make_plane()
    from app.scheduler import ScheduledJob

    plane.scheduler.add(ScheduledJob("s1", "render", NOW))
    plane.materialize_due(NOW)

    with pytest.raises(DispatchError, match="no available node"):
        plane.dispatch("s1", required_capabilities=frozenset({"ffmpeg"}), now=NOW)
