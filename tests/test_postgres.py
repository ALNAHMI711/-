import os
from uuid import uuid4

import pytest

from app.persistence import StoredJob
from app.postgres import PostgresJobRepository


def test_postgres_repository_requires_dsn():
    with pytest.raises(ValueError, match="DSN"):
        PostgresJobRepository("")


def test_postgres_repository_keeps_dsn_private():
    repo = PostgresJobRepository("postgresql://example.invalid/db")
    assert repo._dsn == "postgresql://example.invalid/db"


def test_postgres_job_metadata_survives_repository_recreation():
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        pytest.skip("DATABASE_URL is not configured")
    job_id = f"test_{uuid4().hex}"
    idempotency_key = f"idem_{uuid4().hex}"
    first_repository = PostgresJobRepository(dsn)
    created = first_repository.create(StoredJob(
        job_id=job_id,
        job_type="publish",
        idempotency_key=idempotency_key,
        state="running",
        attempts=1,
        max_attempts=3,
        metadata={
            "youtube_upload": {
                "project_id": "project-a",
                "account_id": "channel-a",
                "offset": 8388608,
                "state": "active",
                "upload_url": "encrypted-session-reference",
            }
        },
    ))

    restarted_repository = PostgresJobRepository(dsn)
    restored = restarted_repository.get(job_id)
    assert restored == created
    assert restored.metadata["youtube_upload"]["offset"] == 8388608
    assert restored.metadata["youtube_upload"]["project_id"] == "project-a"

    restarted_repository.save(StoredJob(
        job_id=restored.job_id,
        job_type=restored.job_type,
        idempotency_key=restored.idempotency_key,
        state=restored.state,
        attempts=restored.attempts,
        max_attempts=restored.max_attempts,
        worker_id=restored.worker_id,
        lease_until=restored.lease_until,
        last_error=restored.last_error,
        metadata={**restored.metadata, "youtube_upload": {
            **restored.metadata["youtube_upload"], "offset": 16777216,
        }},
    ))
    assert first_repository.get(job_id).metadata["youtube_upload"]["offset"] == 16777216

    with first_repository._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE job_id = %s", (job_id,))
