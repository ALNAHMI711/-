from datetime import datetime, timezone

import pytest

from app.persistence import DuplicateStoredJob, InMemoryJobRepository, StoredJob


def job(job_id="j1", key="k1"):
    return StoredJob(
        job_id=job_id,
        job_type="render",
        idempotency_key=key,
        state="queued",
        attempts=0,
        max_attempts=3,
        lease_until=datetime(2026, 9, 14, 22, 5, tzinfo=timezone.utc),
    )


def test_repository_create_get_and_save():
    repo = InMemoryJobRepository()
    created = repo.create(job())
    assert repo.get("j1") == created
    updated = StoredJob(**{**created.__dict__, "state": "running", "attempts": 1})
    assert repo.save(updated).state == "running"
    assert repo.get("j1").attempts == 1


def test_repository_rejects_duplicate_job_or_idempotency_key():
    repo = InMemoryJobRepository()
    repo.create(job())
    with pytest.raises(DuplicateStoredJob):
        repo.create(job())
    with pytest.raises(DuplicateStoredJob):
        repo.create(job(job_id="j2", key="k1"))


def test_repository_save_requires_existing_job():
    repo = InMemoryJobRepository()
    with pytest.raises(KeyError, match="job not found"):
        repo.save(job())
