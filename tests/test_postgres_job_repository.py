import os

import pytest

from app.persistence import StoredJob
from app.postgres import PostgresJobRepository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL is not configured")
def test_postgres_job_repository_round_trips_durable_metadata():
    repository = PostgresJobRepository(os.environ["DATABASE_URL"])
    job = StoredJob(
        job_id="pg_metadata_test",
        job_type="publish",
        idempotency_key="pg_metadata_test",
        state="waiting_provider",
        attempts=1,
        max_attempts=3,
        metadata={
            "youtube_upload": {
                "project_id": "project-1",
                "account_id": "channel-1",
                "offset": 8388608,
                "state": "active",
                "upload_url": "encrypted-session-reference",
            }
        },
    )
    try:
        repository.create(job)
        loaded = repository.get(job.job_id)
        assert loaded.metadata["youtube_upload"]["offset"] == 8388608
        assert loaded.metadata["youtube_upload"]["project_id"] == "project-1"
    finally:
        with repository._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM jobs WHERE job_id = %s", (job.job_id,))
