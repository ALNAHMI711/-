"""Execution boundary for scheduled publishing jobs with durable confirmations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .audit_log import AuditEvent
from .job_queue import Job, JobQueue, JobState
from .persistence import StoredJob
from .publishing import PublishRequest, PublishResult, PublicationState, PublishingService


@dataclass(frozen=True)
class PublishJobPayload:
    project_id: str
    account_id: str
    platform: str
    text: str
    media_url: str | None = None


class PublishJobExecutor:
    def __init__(self, queue: JobQueue, publishing: PublishingService, audit_log, job_repository=None) -> None:
        self._queue = queue
        self._publishing = publishing
        self._audit = audit_log
        self._job_repository = job_repository
        self._pending: dict[str, tuple[PublishJobPayload, str]] = {}

    def _persist(self, job: Job, metadata: dict[str, object] | None = None) -> None:
        if self._job_repository is None:
            return
        previous = self._job_repository.get(job.job_id)
        merged = dict(previous.metadata)
        if metadata:
            merged.update(metadata)
        self._job_repository.save(StoredJob(
            job_id=job.job_id, job_type=job.job_type,
            idempotency_key=job.idempotency_key, state=job.state.value,
            attempts=job.attempts, max_attempts=job.max_attempts,
            worker_id=job.worker_id, lease_until=job.lease_until,
            last_error=job.last_error, metadata=merged,
        ))

    def restore_pending_confirmations(self) -> tuple[str, ...]:
        """Rehydrate WAITING_PROVIDER jobs and pollable context after process restart."""
        if self._job_repository is None:
            return ()
        restored: list[str] = []
        for stored in self._job_repository.list_by_state(JobState.WAITING_PROVIDER.value, "publish"):
            metadata = dict(stored.metadata)
            publish = metadata.get("publish")
            provider_id = str(metadata.get("provider_post_id", "")).strip()
            if not isinstance(publish, dict) or not provider_id:
                continue
            project_id = str(publish.get("project_id", "")).strip()
            account_id = str(publish.get("account_id", "")).strip()
            platform = str(publish.get("platform", "")).strip()
            if not project_id or not account_id or not platform:
                continue
            job = Job(
                job_id=stored.job_id, job_type=stored.job_type,
                idempotency_key=stored.idempotency_key,
                state=JobState.WAITING_PROVIDER, attempts=stored.attempts,
                max_attempts=stored.max_attempts, worker_id=None, lease_until=None,
                last_error=stored.last_error,
            )
            self._queue.restore(job)
            payload = PublishJobPayload(project_id, account_id, platform, text="")
            self._pending[stored.job_id] = (payload, provider_id)
            restored.append(stored.job_id)
        return tuple(restored)

    def enqueue(self, payload: PublishJobPayload, idempotency_key: str) -> Job:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if not payload.project_id.strip() or not payload.account_id.strip():
            raise ValueError("project_id and account_id are required")
        job = Job(job_id=f"pub_{uuid4().hex}", job_type="publish", idempotency_key=idempotency_key.strip())
        if self._job_repository is not None:
            self._job_repository.create(StoredJob(
                job_id=job.job_id, job_type=job.job_type,
                idempotency_key=job.idempotency_key, state=job.state.value,
                attempts=0, max_attempts=job.max_attempts,
                metadata={"publish": {
                    "project_id": payload.project_id, "account_id": payload.account_id,
                    "platform": payload.platform, "media_url": payload.media_url,
                }},
            ))
        self._queue.enqueue(job)
        self._audit.append(AuditEvent(
            f"evt_{uuid4().hex}", "system", "publish_queued",
            payload.project_id, payload.account_id, "queued", datetime.now(timezone.utc),
        ))
        return job

    def run(self, job_id: str, worker_id: str, payload: PublishJobPayload) -> PublishResult:
        job = self._queue.claim(job_id, worker_id)
        self._persist(job)
        try:
            result = self._publishing.publish(PublishRequest(
                project_id=payload.project_id, account_id=payload.account_id,
                platform=payload.platform, text=payload.text,
                media_url=payload.media_url, idempotency_key=job.idempotency_key,
                job_id=job_id,
            ))
        except Exception as exc:
            failed = self._queue.fail(job_id, str(exc), retry=False)
            self._persist(failed)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_failed",
                payload.project_id, payload.account_id, "failed", datetime.now(timezone.utc),
            ))
            raise

        if result.state is PublicationState.PUBLISHING:
            if not result.provider_post_id:
                failed = self._queue.fail(job_id, "provider did not return a confirmation id", retry=False)
                self._persist(failed)
                raise RuntimeError("provider did not return a confirmation id")
            waiting = self._queue.wait_for_provider(job_id)
            self._persist(waiting, {"provider_post_id": result.provider_post_id})
            self._pending[job_id] = (payload, result.provider_post_id)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_waiting_provider",
                payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
            ))
            return result

        if result.state is PublicationState.FAILED:
            failed = self._queue.fail(job_id, result.detail, retry=False)
            self._persist(failed)
            self._pending.pop(job_id, None)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_failed",
                payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
            ))
            return result

        succeeded = self._queue.succeed(job_id)
        self._persist(succeeded, {"provider_post_id": result.provider_post_id, "published_at": datetime.now(timezone.utc).isoformat()})
        self._pending.pop(job_id, None)
        self._audit.append(AuditEvent(
            f"evt_{uuid4().hex}", "system", "publish_completed",
            payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
        ))
        return result

    def confirm(self, job_id: str, payload: PublishJobPayload, provider_post_id: str) -> PublishResult:
        job = self._queue.get(job_id)
        if job.state is not JobState.WAITING_PROVIDER:
            raise ValueError("publish job is not waiting for provider confirmation")
        try:
            result = self._publishing.check_status(
                payload.project_id, payload.account_id, payload.platform, provider_post_id,
            )
        except Exception:
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_status_check_failed",
                payload.project_id, payload.account_id, "failed", datetime.now(timezone.utc),
            ))
            raise

        if result.state is PublicationState.PUBLISHING:
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_still_processing",
                payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
            ))
            return result

        if result.state is PublicationState.FAILED:
            failed = self._queue.fail(job_id, result.detail, retry=False)
            self._persist(failed, {"provider_failure": result.detail})
            self._pending.pop(job_id, None)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_failed",
                payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
            ))
            return result

        succeeded = self._queue.succeed(job_id)
        self._persist(succeeded, {
            "provider_post_id": result.provider_post_id or provider_post_id,
            "provider_url": result.provider_url,
            "published_at": (result.published_at or datetime.now(timezone.utc)).isoformat(),
        })
        self._pending.pop(job_id, None)
        self._audit.append(AuditEvent(
            f"evt_{uuid4().hex}", "system", "publish_completed",
            payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
        ))
        return result

    def poll_provider_confirmations(self) -> tuple[str, ...]:
        completed: list[str] = []
        for job_id, (payload, provider_post_id) in tuple(self._pending.items()):
            job = self._queue.get(job_id)
            if job.state is not JobState.WAITING_PROVIDER:
                self._pending.pop(job_id, None)
                continue
            result = self.confirm(job_id, payload, provider_post_id)
            if result.state in {PublicationState.PUBLISHED, PublicationState.FAILED}:
                completed.append(job_id)
        return tuple(completed)
