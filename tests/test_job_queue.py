from datetime import datetime, timedelta, timezone

import pytest

from app.job_queue import DuplicateJob, InvalidJobTransition, Job, JobQueue, JobState


NOW = datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc)


def make_job(**kwargs):
    values = {"job_id": "job-1", "job_type": "publish", "idempotency_key": "idem-1"}
    values.update(kwargs)
    return Job(**values)


def test_enqueue_is_idempotent() -> None:
    queue = JobQueue()
    queue.enqueue(make_job())
    with pytest.raises(DuplicateJob):
        queue.enqueue(make_job(job_id="job-2"))
    with pytest.raises(DuplicateJob):
        queue.enqueue(make_job(idempotency_key="idem-2"))


def test_claim_and_success_lifecycle() -> None:
    queue = JobQueue()
    queue.enqueue(make_job())
    job = queue.claim("job-1", "worker-1", lease_seconds=60, now=NOW)
    assert job.state is JobState.RUNNING
    assert job.attempts == 1
    assert job.lease_until == NOW + timedelta(seconds=60)
    queue.succeed("job-1")
    assert queue.get("job-1").state is JobState.SUCCEEDED


def test_failure_retries_until_max_attempts_then_fails() -> None:
    queue = JobQueue()
    queue.enqueue(make_job(max_attempts=2))
    queue.claim("job-1", "worker-1", now=NOW)
    queue.fail("job-1", "temporary")
    assert queue.get("job-1").state is JobState.QUEUED
    queue.claim("job-1", "worker-2", now=NOW)
    queue.fail("job-1", "permanent")
    assert queue.get("job-1").state is JobState.FAILED
    assert queue.get("job-1").worker_id is None


def test_expired_lease_is_reclaimed() -> None:
    queue = JobQueue()
    queue.enqueue(make_job(max_attempts=2))
    queue.claim("job-1", "worker-1", lease_seconds=10, now=NOW)
    reclaimed = queue.reclaim_expired(now=NOW + timedelta(seconds=11))
    assert reclaimed == [queue.get("job-1")]
    assert queue.get("job-1").state is JobState.QUEUED


def test_cancel_and_invalid_transitions() -> None:
    queue = JobQueue()
    queue.enqueue(make_job())
    queue.cancel("job-1")
    assert queue.get("job-1").state is JobState.CANCELLED
    with pytest.raises(InvalidJobTransition):
        queue.succeed("job-1")
