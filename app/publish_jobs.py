"""Execution boundary for scheduled publishing jobs.

This layer is deliberately provider-agnostic: it enforces project/account
isolation, idempotency and safe audit events before invoking an official API
publisher.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .audit_log import AuditEvent
from .job_queue import Job, JobQueue
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

    def enqueue(self, payload: PublishJobPayload, idempotency_key: str) -> Job:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if not payload.project_id.strip() or not payload.account_id.strip():
            raise ValueError("project_id and account_id are required")
        job = Job(
            job_id=f"pub_{uuid4().hex}",
            job_type="publish",
            idempotency_key=idempotency_key.strip(),
        )
        self._queue.enqueue(job)
        self._audit.append(AuditEvent(
            f"evt_{uuid4().hex}", "system", "publish_queued",
            payload.project_id, payload.account_id, "queued",
            datetime.now(timezone.utc),
        ))
        return job

    def run(self, job_id: str, worker_id: str, payload: PublishJobPayload) -> PublishResult:
        job = self._queue.claim(job_id, worker_id)
        try:
            result = self._publishing.publish(PublishRequest(
                project_id=payload.project_id,
                account_id=payload.account_id,
                platform=payload.platform,
                text=payload.text,
                media_url=payload.media_url,
                idempotency_key=job.idempotency_key,
            ))
        except Exception as exc:
            self._queue.fail(job_id, str(exc), retry=False)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_failed",
                payload.project_id, payload.account_id, "failed",
                datetime.now(timezone.utc),
            ))
            raise

        if result.state is PublicationState.PUBLISHING:
            self._queue.wait_for_provider(job_id)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_waiting_provider",
                payload.project_id, payload.account_id, result.state.value,
                datetime.now(timezone.utc),
            ))
            return result

        if result.state is PublicationState.FAILED:
            self._queue.fail(job_id, result.detail, retry=False)
            self._audit.append(AuditEvent(
                f"evt_{uuid4().hex}", "system", "publish_failed",
                payload.project_id, payload.account_id, result.state.value,
                datetime.now(timezone.utc),
            ))
            return result

        self._queue.succeed(job_id)
        self._audit.append(AuditEvent(
            f"evt_{uuid4().hex}", "system", "publish_completed",
            payload.project_id, payload.account_id, result.state.value,
            datetime.now(timezone.utc),
        ))
        return result
