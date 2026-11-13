from app.audit_log import InMemoryAuditLog
from app.job_queue import JobQueue, JobState
from app.persistence import InMemoryJobRepository
from app.publish_jobs import PublishJobExecutor, PublishJobPayload
from app.publishing import PublishResult, PublicationState


class PendingThenConfirmed:
    def publish(self, request):
        return PublishResult(PublicationState.PUBLISHING, provider_post_id="yt-video-42")

    def check_status(self, project_id, account_id, platform, provider_post_id):
        assert (project_id, account_id, platform, provider_post_id) == (
            "project-7", "channel-9", "youtube", "yt-video-42"
        )
        return PublishResult(
            PublicationState.PUBLISHED, provider_post_id="yt-video-42",
            provider_url="https://youtube.com/watch?v=yt-video-42",
        )


def test_waiting_provider_job_is_restored_after_executor_restart():
    repo = InMemoryJobRepository()
    audit = InMemoryAuditLog()
    payload = PublishJobPayload("project-7", "channel-9", "youtube", "title", "https://assets.example/video.mp4")

    first_queue = JobQueue()
    first = PublishJobExecutor(first_queue, PendingThenConfirmed(), audit, job_repository=repo)
    job = first.enqueue(payload, "idempotency-restart")
    first.run(job.job_id, "worker-a", payload)
    assert first_queue.get(job.job_id).state is JobState.WAITING_PROVIDER
    persisted = repo.get(job.job_id)
    assert persisted.state == JobState.WAITING_PROVIDER.value
    assert persisted.metadata["provider_post_id"] == "yt-video-42"

    restarted_queue = JobQueue()
    restarted = PublishJobExecutor(restarted_queue, PendingThenConfirmed(), audit, job_repository=repo)
    assert restarted.restore_pending_confirmations() == (job.job_id,)
    assert restarted_queue.get(job.job_id).state is JobState.WAITING_PROVIDER

    assert restarted.poll_provider_confirmations() == (job.job_id,)
    assert restarted_queue.get(job.job_id).state is JobState.SUCCEEDED
    assert repo.get(job.job_id).state == JobState.SUCCEEDED.value
    assert restarted.poll_provider_confirmations() == ()


def test_restore_skips_incomplete_pending_job_metadata():
    repo = InMemoryJobRepository()
    from app.persistence import StoredJob
    repo.create(StoredJob(
        job_id="pub_bad", job_type="publish", idempotency_key="bad",
        state=JobState.WAITING_PROVIDER.value, attempts=1, max_attempts=3,
        metadata={"publish": {"project_id": "p", "account_id": "a", "platform": "youtube"}},
    ))
    executor = PublishJobExecutor(JobQueue(), PendingThenConfirmed(), InMemoryAuditLog(), job_repository=repo)
    assert executor.restore_pending_confirmations() == ()
