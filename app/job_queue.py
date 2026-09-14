"""Framework-neutral job queue primitives for Mashahid.

The queue models lifecycle, idempotency and leases. Persistence and distributed
locking belong to the production adapter (PostgreSQL/Redis), not this domain
layer.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    job_id: str
    job_type: str
    idempotency_key: str
    state: JobState = JobState.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    worker_id: str | None = None
    lease_until: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id.strip() or not self.job_type.strip() or not self.idempotency_key.strip():
            raise ValueError("job_id, job_type and idempotency_key are required")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")


class DuplicateJob(ValueError):
    """Raised when an idempotency key is already present."""


class JobNotFound(KeyError):
    """Raised when a requested job does not exist."""


class InvalidJobTransition(ValueError):
    """Raised when a lifecycle transition is not permitted."""


class JobQueue:
    """In-memory reference implementation used by tests/dev."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._keys: dict[str, str] = {}

    def enqueue(self, job: Job) -> Job:
        if job.job_id in self._jobs:
            raise DuplicateJob(job.job_id)
        if job.idempotency_key in self._keys:
            raise DuplicateJob(job.idempotency_key)
        self._jobs[job.job_id] = job
        self._keys[job.idempotency_key] = job.job_id
        return job

    def get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise JobNotFound(job_id) from exc

    def claim(self, job_id: str, worker_id: str, lease_seconds: int = 300, now: datetime | None = None) -> Job:
        if not worker_id.strip() or lease_seconds < 1:
            raise ValueError("worker_id and positive lease_seconds are required")
        job = self.get(job_id)
        if job.state is not JobState.QUEUED:
            raise InvalidJobTransition(f"cannot claim {job.state.value}")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        job.state = JobState.RUNNING
        job.attempts += 1
        job.worker_id = worker_id
        job.lease_until = current + timedelta(seconds=lease_seconds)
        job.last_error = None
        return job

    def renew(self, job_id: str, worker_id: str, lease_seconds: int = 300,
              now: datetime | None = None) -> Job:
        if not worker_id.strip() or lease_seconds < 1:
            raise ValueError("worker_id and positive lease_seconds are required")
        job = self.get(job_id)
        if job.state is not JobState.RUNNING or job.worker_id != worker_id:
            raise InvalidJobTransition("only the owning worker can renew a running job")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        job.lease_until = current + timedelta(seconds=lease_seconds)
        return job

    def succeed(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.state is not JobState.RUNNING:
            raise InvalidJobTransition("only running jobs can succeed")
        job.state = JobState.SUCCEEDED
        job.lease_until = None
        return job

    def fail(self, job_id: str, error: str, retry: bool = True) -> Job:
        job = self.get(job_id)
        if job.state is not JobState.RUNNING:
            raise InvalidJobTransition("only running jobs can fail")
        job.last_error = error.strip()[:500] or "job failed"
        job.lease_until = None
        job.worker_id = None
        if retry and job.attempts < job.max_attempts:
            job.state = JobState.QUEUED
        else:
            job.state = JobState.FAILED
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.state not in {JobState.QUEUED, JobState.RUNNING}:
            raise InvalidJobTransition("only queued or running jobs can be cancelled")
        job.state = JobState.CANCELLED
        job.lease_until = None
        return job

    def reclaim_expired(self, now: datetime | None = None) -> list[Job]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        reclaimed: list[Job] = []
        for job in self._jobs.values():
            if job.state is JobState.RUNNING and job.lease_until and job.lease_until <= current:
                job.worker_id = None
                job.lease_until = None
                if job.attempts < job.max_attempts:
                    job.state = JobState.QUEUED
                else:
                    job.state = JobState.FAILED
                    job.last_error = job.last_error or "worker lease expired"
                reclaimed.append(job)
        return reclaimed
