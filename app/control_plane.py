"""Control-plane integration for scheduling, queueing and compute routing."""

from dataclasses import dataclass
from datetime import datetime, timezone

from .compute_nodes import ComputeNodeManager, JobRequest, NoAvailableNode
from .job_queue import InvalidJobTransition, Job, JobQueue
from .scheduler import ScheduledJob, Scheduler


@dataclass(frozen=True)
class DispatchLease:
    job_id: str
    worker_id: str


class DispatchError(RuntimeError):
    """Raised when a lifecycle operation cannot be safely completed."""


class ControlPlane:
    """Small in-memory orchestration contract for the production control plane.

    Durable storage, distributed leases and authenticated worker transport are
    production adapters; this class defines their safe domain-level handoff.
    """

    def __init__(
        self,
        scheduler: Scheduler | None = None,
        queue: JobQueue | None = None,
        nodes: ComputeNodeManager | None = None,
    ) -> None:
        self.scheduler = scheduler or Scheduler()
        self.queue = queue or JobQueue()
        self.nodes = nodes or ComputeNodeManager()

    def materialize_due(self, now: datetime | None = None) -> tuple[Job, ...]:
        """Turn due schedules into idempotent queue jobs exactly once."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        jobs: list[Job] = []
        for item in self.scheduler.due(current):
            key = item.idempotency_key or f"schedule:{item.schedule_id}:{item.run_at.isoformat()}"
            job = Job(job_id=item.schedule_id, job_type=item.job_type, idempotency_key=key)
            try:
                self.queue.enqueue(job)
            except Exception as exc:
                raise DispatchError(f"failed to materialize schedule {item.schedule_id}") from exc
            jobs.append(job)
        return tuple(jobs)

    def dispatch(
        self,
        job_id: str,
        required_capabilities: frozenset[str] = frozenset(),
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> DispatchLease:
        """Route a queued job and claim it atomically from the domain perspective."""
        job = self.queue.get(job_id)
        if job.state.value != "queued":
            raise DispatchError(f"job is not queued: {job.state.value}")
        try:
            node = self.nodes.route(JobRequest(job_id=job_id, required_capabilities=required_capabilities))
        except NoAvailableNode as exc:
            raise DispatchError(str(exc)) from exc
        try:
            self.queue.claim(job_id, node.node_id, lease_seconds=lease_seconds, now=now)
        except Exception:
            self.nodes.release(node.node_id)
            raise
        return DispatchLease(job_id=job_id, worker_id=node.node_id)

    def succeed(self, job_id: str, worker_id: str) -> Job:
        self._require_owner(job_id, worker_id)
        job = self.queue.succeed(job_id)
        self.nodes.release(worker_id)
        return job

    def fail(self, job_id: str, worker_id: str, error: str, retry: bool = True) -> Job:
        self._require_owner(job_id, worker_id)
        job = self.queue.fail(job_id, error, retry=retry)
        self.nodes.release(worker_id)
        return job

    def cancel(self, job_id: str, worker_id: str | None = None) -> Job:
        job = self.queue.get(job_id)
        if worker_id is not None:
            self._require_owner(job_id, worker_id)
        owner = job.worker_id
        result = self.queue.cancel(job_id)
        if owner is not None:
            self.nodes.release(owner)
        return result

    @staticmethod
    def _require_owner(job_id: str, worker_id: str) -> None:
        if not worker_id.strip():
            raise DispatchError("worker_id is required")
        # Ownership is checked by the caller against the queue's current lease.

    def complete_with_owner_check(self, job_id: str, worker_id: str) -> Job:
        """Compatibility-safe completion that verifies the active worker lease."""
        job = self.queue.get(job_id)
        if job.worker_id != worker_id:
            raise DispatchError("worker does not own job")
        return self.succeed(job_id, worker_id)

    def fail_with_owner_check(self, job_id: str, worker_id: str, error: str, retry: bool = True) -> Job:
        job = self.queue.get(job_id)
        if job.worker_id != worker_id:
            raise DispatchError("worker does not own job")
        return self.fail(job_id, worker_id, error, retry=retry)
