from datetime import datetime, timezone, timedelta

import pytest

from app.worker_commands import (
    CommandRejected,
    CommandStatus,
    CommandType,
    WorkerCommand,
    WorkerCommandLedger,
)


def command(expires=110.0, worker="worker-1"):
    return WorkerCommand(
        command_id="cmd-1",
        command_type=CommandType.EXECUTE_JOB,
        worker_id=worker,
        job_id="job-1",
        job_type="render",
        issued_at=datetime.fromtimestamp(100, tz=timezone.utc),
        expires_at=datetime.fromtimestamp(expires, tz=timezone.utc),
    )


def test_command_requires_timezone_and_valid_window():
    with pytest.raises(ValueError):
        WorkerCommand("c", CommandType.DRAIN, "w", None, None, datetime.now(), datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        WorkerCommand("c", CommandType.DRAIN, "w", None, None, datetime.fromtimestamp(100, timezone.utc), datetime.fromtimestamp(100, timezone.utc))


def test_execute_command_requires_job_metadata():
    with pytest.raises(ValueError):
        WorkerCommand("c", CommandType.EXECUTE_JOB, "w", None, None, datetime.fromtimestamp(100, timezone.utc), datetime.fromtimestamp(110, timezone.utc))


def test_ledger_rejects_wrong_worker_and_expired_command():
    ledger = WorkerCommandLedger()
    with pytest.raises(CommandRejected):
        ledger.accept(command(), "worker-2", now=datetime.fromtimestamp(101, timezone.utc))
    with pytest.raises(CommandRejected):
        ledger.accept(command(expires=101), "worker-1", now=datetime.fromtimestamp(101, timezone.utc))


def test_ledger_is_idempotent_and_enforces_finish_ownership():
    ledger = WorkerCommandLedger()
    cmd = command()
    first = ledger.accept(cmd, "worker-1", now=datetime.fromtimestamp(101, timezone.utc))
    second = ledger.accept(cmd, "worker-1", now=datetime.fromtimestamp(102, timezone.utc))
    assert first == second
    with pytest.raises(CommandRejected):
        ledger.finish(cmd.command_id, "worker-2", True)
    done = ledger.finish(cmd.command_id, "worker-1", True)
    assert done.status is CommandStatus.SUCCEEDED
    assert ledger.finish(cmd.command_id, "worker-1", False) == done


def test_failed_result_is_bounded():
    ledger = WorkerCommandLedger()
    cmd = command()
    ledger.accept(cmd, "worker-1", now=datetime.fromtimestamp(101, timezone.utc))
    result = ledger.finish(cmd.command_id, "worker-1", False, "x" * 1000)
    assert result.status is CommandStatus.FAILED
    assert len(result.error) == 500
