from datetime import datetime, timezone

import pytest

from app.compute_nodes import ComputeNode, ComputeNodeManager, NodeKind, NodeState
from app.control_plane import ControlPlane, DispatchError
from app.job_queue import Job
from app.worker_command_handler import WorkerCommandHandler, WorkerCommandHandlerError
from app.worker_commands import CommandType, WorkerCommand

NOW = datetime.fromtimestamp(1_000, timezone.utc)
EXPIRES = datetime.fromtimestamp(1_030, timezone.utc)


def make_command(command_type, worker_id="w1", job_id="job-1", job_type="content_publish"):
    return WorkerCommand(
        command_id=f"cmd-{command_type.value}",
        command_type=command_type,
        worker_id=worker_id,
        job_id=job_id,
        job_type=job_type,
        issued_at=NOW,
        expires_at=EXPIRES,
    )


def make_plane():
    nodes = ComputeNodeManager([
        ComputeNode("w1", "worker-1", NodeKind.PRIVATE, state=NodeState.ONLINE),
        ComputeNode("w2", "worker-2", NodeKind.FREE_TIER, state=NodeState.ONLINE),
    ])
    plane = ControlPlane(nodes=nodes)
    plane.queue.enqueue(Job("job-1", "content_publish", "idem-1"))
    plane.dispatch("job-1", now=NOW)
    return plane, nodes


def test_execute_requires_owned_job_and_calls_callback_once():
    plane, nodes = make_plane()
    calls = []
    handler = WorkerCommandHandler(plane, nodes, execute_callback=lambda command: calls.append(command.job_id) or True)

    handler(make_command(CommandType.EXECUTE_JOB))

    assert calls == ["job-1"]
    assert plane.queue.get("job-1").worker_id == "w1"


def test_execute_rejects_wrong_worker_ownership_without_callback():
    plane, nodes = make_plane()
    calls = []
    handler = WorkerCommandHandler(plane, nodes, execute_callback=lambda command: calls.append(command) or True)

    with pytest.raises(WorkerCommandHandlerError, match="does not own"):
        handler(make_command(CommandType.EXECUTE_JOB, worker_id="w2"))

    assert calls == []


def test_execute_rejects_job_type_mismatch():
    plane, nodes = make_plane()
    handler = WorkerCommandHandler(plane, nodes, execute_callback=lambda command: True)

    with pytest.raises(WorkerCommandHandlerError, match="job type mismatch"):
        handler(make_command(CommandType.EXECUTE_JOB, job_type="different"))


def test_cancel_is_authorized_by_job_owner():
    plane, nodes = make_plane()
    handler = WorkerCommandHandler(plane, nodes, execute_callback=lambda command: True)

    handler(make_command(CommandType.CANCEL_JOB))

    assert plane.queue.get("job-1").state.value == "cancelled"


def test_cancel_rejects_non_owner():
    plane, nodes = make_plane()
    handler = WorkerCommandHandler(plane, nodes, execute_callback=lambda command: True)

    with pytest.raises(WorkerCommandHandlerError):
        handler(make_command(CommandType.CANCEL_JOB, worker_id="w2"))

    assert plane.queue.get("job-1").state.value == "running"


def test_drain_marks_only_target_worker():
    plane, nodes = make_plane()
    handler = WorkerCommandHandler(plane, nodes, execute_callback=lambda command: True)

    handler(make_command(CommandType.DRAIN))

    assert nodes.get("w1").state is NodeState.DRAINING
    assert nodes.get("w2").state is NodeState.ONLINE


def test_drain_rejects_unknown_worker():
    plane, nodes = make_plane()
    handler = WorkerCommandHandler(plane, nodes, execute_callback=lambda command: True)

    with pytest.raises(WorkerCommandHandlerError, match="unknown worker"):
        handler(make_command(CommandType.DRAIN, worker_id="missing"))


def test_execute_callback_failure_does_not_leak_exception_details():
    plane, nodes = make_plane()

    def explode(command):
        raise RuntimeError("secret-token-must-not-leak")

    handler = WorkerCommandHandler(plane, nodes, execute_callback=explode)
    with pytest.raises(WorkerCommandHandlerError) as exc:
        handler(make_command(CommandType.EXECUTE_JOB))
    assert "secret-token" not in str(exc.value)
