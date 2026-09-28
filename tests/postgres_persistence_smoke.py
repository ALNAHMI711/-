"""CI smoke test for durable PostgreSQL job metadata."""

import os
from datetime import datetime, timezone

from app.persistence import StoredJob
from app.postgres import PostgresJobRepository


def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    repo = PostgresJobRepository(dsn)
    job = StoredJob(
        job_id="ci-postgres-recovery",
        job_type="publish",
        idempotency_key="ci-postgres-recovery",
        state="running",
        attempts=1,
        max_attempts=3,
        metadata={
            "youtube_upload": {
                "project_id": "project-ci",
                "account_id": "channel-ci",
                "platform": "youtube",
                "offset": 8388608,
                "state": "active",
            }
        },
    )
    try:
        repo.create(job)
        restored = repo.get(job.job_id)
        assert restored.metadata["youtube_upload"]["offset"] == 8388608
        assert restored.metadata["youtube_upload"]["project_id"] == "project-ci"
        print("PostgreSQL durable job metadata: OK")
    finally:
        with repo._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM jobs WHERE job_id = %s", (job.job_id,))


if __name__ == "__main__":
    main()
