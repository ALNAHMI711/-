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
    """In-memory orchestration contract; durable adapters belong to production."""

    def __init__(self, scheduler=None, queue=None, nodes=None, command_ledger=None) -> None:
        self.scheduler = scheduler or Scheduler()
        self.queue = queue or JobQueue()
        self.nodes = nodes or ComputeNodeManager()
        self.command_ledger = command_ledger or WorkerCommandLedger()

    def materialize_due(self, now: datetime | None = None) -> tuple[Job, ...]:
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
        job = self.queue.get(job_id)
        if job.state.value != "queued":
            raise DispatchError(f"job is not queued: {job.state.value}")
        issued_at = now or datetime.now(timezone.utc)
        if issued_at.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        try:
            node = self.nodes.route(JobRequest(job_id=job_id, required_capabilities=required_capabilities))
        except NoAvailableNode as exc:
            raise DispatchError(str(exc)) from exc
        try:
            self.queue.claim(job_id, node.node_id, lease_seconds=lease_seconds, now=issued_at)
            command = WorkerCommand(
                command_id=f"cmd:{job_id}:{job.attempts}",
                command_type=CommandType.EXECUTE_JOB,
                worker_id=node.node_id,
                job_id=job_id,
                job_type=job.job_type,
                issued_at=issued_at,
                expires_at=job.lease_until,
            )
            self.command_ledger.accept(command, node.node_id, now=issued_at)
        except Exception:
            try:
                self.queue.fail(job_id, "worker dispatch setup failed", retry=False)
            except Exception:
                pass
            self.nodes.release(node.node_id)
            raise
        return DispatchLease(job_id=job_id, worker_id=node.node_id, command=command)

    def succeed(self, job_id: str, worker_id: str) -> Job:
        job = self._owned_job(job_id, worker_id)
        result = self.queue.succeed(job_id)
        self.command_ledger.finish(self._command_id(job), worker_id, True)
        self.nodes.release(worker_id)
        return result

    def fail(self, job_id: str, worker_id: str, error: str, retry: bool = True) -> Job:
        job = self._owned_job(job_id, worker_id)
        result = self.queue.fail(job_id, error, retry=retry)
        self.command_ledger.finish(self._command_id(job), worker_id, False, error)
        self.nodes.release(worker_id)
        return result

    def cancel(self, job_id: str, worker_id: str | None = None) -> Job:
        job = self.queue.get(job_id)
        if job.worker_id is not None and job.worker_id != worker_id:
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

    @staticmethod
    def _command_id(job: Job) -> str:
        return f"cmd:{job.job_id}:{job.attempts}"
