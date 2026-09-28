"""Execution boundary for scheduled publishing jobs.

This layer is deliberately provider-agnostic: it enforces project/account
isolation, idempotency and safe audit events before invoking an official API
publisher.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .audit_log import AuditEvent
from .job_queue import Job, JobQueue, JobState
from .publishing import PublishRequest, PublishResult, PublicationState, PublishingService


@dataclass(frozen=True)
class PublishJobPayload:
    project_id: str
    account_id: str
    platform: str
    text: str
    media_url: str | None = None


class PublishJobExecutor:
    def __init__(self, queue: JobQueue, publishing: PublishingService, audit_log) -> None:
        self._queue = queue
        self._publishing = publishing
        self._audit = audit_log
        self._pending: dict[str, tuple[PublishJobPayload, str]] = {}

    def enqueue(self, payload: PublishJobPayload, idempotency_key: str) -> Job:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if not payload.project_id.strip() or not payload.account_id.strip():
            raise ValueError("project_id and account_id are required")
        job = Job(job_id=f"pub_{uuid4().hex}", job_type="publish", idempotency_key=idempotency_key.strip())
        self._queue.enqueue(job)
        self._audit.append(AuditEvent(
            f"evt_{uuid4().hex}", "system", "publish_queued",
            payload.project_id, payload.account_id, "queued", datetime.now(timezone.utc),
        ))
        return job

    def run(self, job_id: str, worker_id: str, payload: PublishJobPayload) -> PublishResult:
        job = self._queue.claim(job_id, worker_id)
        try:
            result = self._publishing.publish(PublishRequest(
                project_id=payload.project_id, account_id=payload.account_id,
                platform=payload.platform, text=payload.text,
                media_url=payload.media_url, idempotency_key=job.idempotency_key,
            ))
        except Exception as exc:
            self._queue.fail(job_id, str(exc), retry=False)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_failed",
                payload.project_id, payload.account_id, "failed", datetime.now(timezone.utc),
            ))
            raise

        if result.state is PublicationState.PUBLISHING:
            if not result.provider_post_id:
                self._queue.fail(job_id, "provider did not return a confirmation id", retry=False)
                raise RuntimeError("provider did not return a confirmation id")
            self._queue.wait_for_provider(job_id)
            self._pending[job_id] = (payload, result.provider_post_id)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_waiting_provider",
                payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
            ))
            return result

        if result.state is PublicationState.FAILED:
            self._pending.pop(job_id, None)
            self._queue.fail(job_id, result.detail, retry=False)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_failed",
                payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
            ))
            return result

        self._queue.succeed(job_id)
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
        except Exception as exc:
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
            self._queue.fail(job_id, result.detail, retry=False)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_failed",
                payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
            ))
            return result

        self._queue.succeed(job_id)
        self._audit.append(AuditEvent(
            f"evt_{uuid4().hex}", "system", "publish_completed",
            payload.project_id, payload.account_id, result.state.value, datetime.now(timezone.utc),
        ))
        return result

    def poll_provider_confirmations(self) -> tuple[str, ...]:
        """Confirm only jobs currently waiting for a provider response."""
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
