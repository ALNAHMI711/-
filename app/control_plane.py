"""Control-plane integration for scheduling, queueing and compute routing."""

from dataclasses import dataclass
from datetime import datetime, timezone

from .compute_nodes import ComputeNodeManager, JobRequest, NoAvailableNode
from .job_queue import DuplicateJob, Job, JobQueue
from .scheduler import Scheduler
from .worker_commands import CommandType, WorkerCommand, WorkerCommandLedger


@dataclass(frozen=True)
class DispatchLease:
    job_id: str
    worker_id: str
    command: WorkerCommand


class DispatchError(RuntimeError):
    """Raised when a lifecycle operation cannot be safely completed."""


class ControlPlane:
    """Small in-memory orchestration contract for the production control plane.

    Durable storage, distributed leases and authenticated worker transport are
    production adapters; this class defines their safe domain-level handoff.
    """

    def __init__(self, scheduler=None, queue=None, nodes=None, command_ledger=None) -> None:
        self.scheduler = scheduler or Scheduler()
        self.queue = queue or JobQueue()
        self.nodes = nodes or ComputeNodeManager()
        self.command_ledger = command_ledger or WorkerCommandLedger()

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
            except DuplicateJob as exc:
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
        """Route a queued job, claim it, and create its expiring worker command."""
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
        issued_at = now or datetime.now(timezone.utc)
        if issued_at.tzinfo is None:
            self.nodes.release(node.node_id)
            raise ValueError("now must be timezone-aware")
        command = WorkerCommand(
            command_id=f"cmd:{job_id}:{job.attempts}",
            command_type=CommandType.EXECUTE_JOB,
            worker_id=node.node_id,
            job_id=job_id,
            job_type=job.job_type,
            issued_at=issued_at,
            expires_at=job.lease_until,
        )
        try:
            self.command_ledger.accept(command, node.node_id, now=issued_at)
        except Exception:
            self.queue.fail(job_id, "worker command creation failed", retry=False)
            self.nodes.release(node.node_id)
            raise
        return DispatchLease(job_id=job_id, worker_id=node.node_id, command=command)

    def succeed(self, job_id: str, worker_id: str) -> Job:
        job = self._owned_job(job_id, worker_id)
        result = self.queue.succeed(job.job_id)
        self.nodes.release(worker_id)
        self.command_ledger.finish(job.job_id and job.job_id and f"cmd:{job.job_id}:{job.attempts}", worker_id, True)
        return result

    def fail(self, job_id: str, worker_id: str, error: str, retry: bool = True) -> Job:
        job = self._owned_job(job_id, worker_id)
        result = self.queue.fail(job.job_id, error, retry=retry)
        self.nodes.release(worker_id)
        self.command_ledger.finish(f"cmd:{job.job_id}:{job.attempts}", worker_id, False, error)
        return result

    def cancel(self, job_id: str, worker_id: str | None = None) -> Job:
        job = self.queue.get(job_id)
        if worker_id is not None and job.worker_id != worker_id:
            raise DispatchError("worker does not own job")
        owner = job.worker_id
        result = self.queue.cancel(job_id)
        if owner is not None:
            self.nodes.release(owner)
        return result

    def _owned_job(self, job_id: str, worker_id: str) -> Job:
        if not worker_id.strip():
            raise DispatchError("worker_id is required")
        job = self.queue.get(job_id)
        if job.worker_id != worker_id:
            raise DispatchError("worker does not own job")
        return job

    def complete_with_owner_check(self, job_id: str, worker_id: str) -> Job:
        return self.succeed(job_id, worker_id)

    def fail_with_owner_check(self, job_id: str, worker_id: str, error: str, retry: bool = True) -> Job:
        return self.fail(job_id, worker_id, error, retry=retry)
