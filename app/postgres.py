"""PostgreSQL repository adapter for durable Mashahid job state.

The adapter uses parameterized SQL and keeps secrets out of job records. It is
an infrastructure adapter; orchestration code should depend on JobRepository.
"""

from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .persistence import DuplicateStoredJob, StoredJob


class PostgresJobRepository:
    """Transactional PostgreSQL implementation of the job repository contract."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN is required")
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    @staticmethod
    def _to_job(row: dict[str, Any]) -> StoredJob:
        return StoredJob(
            job_id=row["job_id"],
            job_type=row["job_type"],
            idempotency_key=row["idempotency_key"],
            state=row["state"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            worker_id=row["worker_id"],
            lease_until=row["lease_until"],
            last_error=row["last_error"],
        )

    def create(self, job: StoredJob) -> StoredJob:
        if not job.job_id.strip() or not job.idempotency_key.strip():
            raise ValueError("job_id and idempotency_key are required")
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO jobs
                        (job_id, job_type, idempotency_key, state, attempts,
                         max_attempts, worker_id, lease_until, last_error)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING job_id, job_type, idempotency_key, state,
                                  attempts, max_attempts, worker_id, lease_until,
                                  last_error
                        """,
                        (job.job_id, job.job_type, job.idempotency_key, job.state,
                         job.attempts, job.max_attempts, job.worker_id,
                         job.lease_until, job.last_error),
                    )
                    return self._to_job(cur.fetchone())
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateStoredJob(job.job_id) from exc

    def get(self, job_id: str) -> StoredJob:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT job_id, job_type, idempotency_key, state, attempts, "
                    "max_attempts, worker_id, lease_until, last_error "
                    "FROM jobs WHERE job_id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise KeyError(f"job not found: {job_id}")
                return self._to_job(row)

    def save(self, job: StoredJob) -> StoredJob:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE jobs SET job_type=%s, idempotency_key=%s, state=%s,
                        attempts=%s, max_attempts=%s, worker_id=%s,
                        lease_until=%s, last_error=%s
                    WHERE job_id=%s
                    RETURNING job_id, job_type, idempotency_key, state,
                              attempts, max_attempts, worker_id, lease_until,
                              last_error
                    """,
                    (job.job_type, job.idempotency_key, job.state, job.attempts,
                     job.max_attempts, job.worker_id, job.lease_until,
                     job.last_error, job.job_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise KeyError(f"job not found: {job.job_id}")
                return self._to_job(row)
