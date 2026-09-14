"""Persistence contracts for Mashahid's control plane.

The domain layer depends on small repository interfaces so PostgreSQL can be
introduced without coupling orchestration code to a specific ORM. The in-memory
implementation is deterministic and intended for tests only.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class StoredJob:
    job_id: str
    job_type: str
    idempotency_key: str
    state: str
    attempts: int
    max_attempts: int
    worker_id: str | None = None
    lease_until: datetime | None = None
    last_error: str | None = None


class JobRepository(Protocol):
    def create(self, job: StoredJob) -> StoredJob: ...
    def get(self, job_id: str) -> StoredJob: ...
    def save(self, job: StoredJob) -> StoredJob: ...


class DuplicateStoredJob(ValueError):
    """Raised when a job id or idempotency key already exists."""


class InMemoryJobRepository:
    """Reference repository for unit tests; not a production persistence layer."""

    def __init__(self) -> None:
        self._jobs: dict[str, StoredJob] = {}
        self._idempotency: dict[str, str] = {}

    def create(self, job: StoredJob) -> StoredJob:
        if job.job_id in self._jobs or job.idempotency_key in self._idempotency:
            raise DuplicateStoredJob(job.job_id)
        self._jobs[job.job_id] = job
        self._idempotency[job.idempotency_key] = job.job_id
        return job

    def get(self, job_id: str) -> StoredJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"job not found: {job_id}") from exc

    def save(self, job: StoredJob) -> StoredJob:
        if job.job_id not in self._jobs:
            raise KeyError(f"job not found: {job.job_id}")
        self._jobs[job.job_id] = job
        return job
