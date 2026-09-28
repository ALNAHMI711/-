from app.account_connections import AccountConnection, ConnectionState, VerificationState, MonetizationState
from app.audit_log import InMemoryAuditLog
from app.credential_vault import CredentialRef
from app.job_queue import JobQueue, JobState
from app.publish_jobs import PublishJobExecutor, PublishJobPayload
from app.publishing import PublishResult, PublicationState


class Accounts:
    def get(self, project_id, account_id):
        return AccountConnection(
            account_id=account_id, platform="linkedin", display_name="Member",
            project_id=project_id, connection_state=ConnectionState.CONNECTED,
            verification_state=VerificationState.VERIFIED,
            monetization_state=MonetizationState.UNKNOWN,
            permissions=("w_member_social",),
        )


class Vault:
    def find_for_account(self, platform, account_id):
        return CredentialRef("cred-1", platform, account_id, ("w_member_social",))

    def get_secret(self, ref):
        return ("secret", None)


class Publisher:
    platform = "linkedin"

    def publish(self, request, access_token):
        return PublishResult(PublicationState.PUBLISHED, provider_post_id="post-1")


class Service:
    def __init__(self):
        from app.publishing import PublishingService
        self.inner = PublishingService({"linkedin": Publisher()}, Accounts(), Vault())

    def publish(self, request):
        return self.inner.publish(request)


def test_publish_job_is_audited_and_completed():
    audit = InMemoryAuditLog()
    queue = JobQueue()
    executor = PublishJobExecutor(queue, Service(), audit)
    payload = PublishJobPayload("project-1", "member-1", "linkedin", "hello")
    job = executor.enqueue(payload, "project-1:member-1:content-1")
    result = executor.run(job.job_id, "worker-1", payload)
    assert result.state is PublicationState.PUBLISHED
    assert queue.get(job.job_id).state is JobState.SUCCEEDED
    events = audit.list_for_project("project-1")
    assert [e.action for e in events] == ["publish_queued", "publish_completed"]


def test_publish_job_failure_is_audited():
    class FailingService:
        def publish(self, request):
            raise RuntimeError("provider unavailable")

    audit = InMemoryAuditLog()
    queue = JobQueue()
    executor = PublishJobExecutor(queue, FailingService(), audit)
    payload = PublishJobPayload("project-1", "member-1", "linkedin", "hello")
    job = executor.enqueue(payload, "project-1:member-1:content-2")
    try:
        executor.run(job.job_id, "worker-1", payload)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected provider failure")
    assert queue.get(job.job_id).state is JobState.FAILED
    assert audit.list_for_project("project-1")[-1].action == "publish_failed"


def test_publish_job_waits_for_provider_confirmation():
    class PendingService:
        def publish(self, request):
            return PublishResult(
                PublicationState.PUBLISHING,
                provider_post_id="publish-123",
                detail="awaiting provider confirmation",
            )

    audit = InMemoryAuditLog()
    queue = JobQueue()
    executor = PublishJobExecutor(queue, PendingService(), audit)
    payload = PublishJobPayload("project-1", "member-1", "tiktok", "hello")
    job = executor.enqueue(payload, "project-1:member-1:content-3")
    result = executor.run(job.job_id, "worker-1", payload)

    assert result.state is PublicationState.PUBLISHING
    assert result.provider_post_id == "publish-123"
    assert queue.get(job.job_id).state is JobState.WAITING_PROVIDER
    assert audit.list_for_project("project-1")[-1].action == "publish_waiting_provider"
