"""PostgreSQL round-trip test for resumable upload metadata."""

import os
from secrets import token_bytes

import pytest

from app.persistence import StoredJob
from app.postgres import PostgresJobRepository
from app.publishing import PublishRequest, PublicationState, YouTubeVideoPublisher


DSN = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not configured")


class Response:
    status_code = 200
    headers = {}

    def __init__(self, body=None, headers=None):
        self._body = body or {"id": "youtube-recovered"}
        self.headers = headers or {}

    def json(self):
        return self._body


class StartAndInterruptTransport:
    def post(self, url, *, headers, json):
        return Response({}, {"location": "https://upload.example/durable-session"})

    def upload_video_resumable(self, upload_url, media_url, *, headers, start_offset=0, on_progress=None):
        if on_progress:
            on_progress(4096)
        raise RuntimeError("simulated worker termination")


class ResumeTransport:
    def __init__(self):
        self.offset = None

    def post(self, url, *, headers, json):
        raise AssertionError("must reuse the persisted upload session")

    def upload_video_resumable(self, upload_url, media_url, *, headers, start_offset=0, on_progress=None):
        self.offset = start_offset
        assert upload_url == "https://upload.example/durable-session"
        if on_progress:
            on_progress(8192)
        return Response({"id": "youtube-recovered"})


def test_youtube_upload_session_persists_across_repository_recreation():
    repo = PostgresJobRepository(DSN)
    job_id = "pg-recovery-" + token_bytes(8).hex()
    repo.create(StoredJob(
        job_id=job_id, job_type="publish", idempotency_key="idem-" + job_id,
        state="running", attempts=1, max_attempts=3,
    ))
    key = token_bytes(32)
    request = PublishRequest(
        "project-postgres", "channel-postgres", "youtube", "Integration video",
        media_url="https://media.example/video.mp4", job_id=job_id,
    )
    try:
        with pytest.raises(RuntimeError, match="simulated worker termination"):
            YouTubeVideoPublisher(StartAndInterruptTransport(), repo, key).publish(request, "test-token")

        # Simulate a new process constructing a new repository adapter.
        restarted_repo = PostgresJobRepository(DSN)
        stored = restarted_repo.get(job_id)
        saved_session = stored.metadata["youtube_upload"]
        assert saved_session["offset"] == 4096
        assert "https://upload.example/durable-session" not in str(saved_session["upload_url"])

        transport = ResumeTransport()
        result = YouTubeVideoPublisher(transport, restarted_repo, key).publish(request, "test-token")
        assert result.state is PublicationState.PUBLISHED
        assert result.provider_post_id == "youtube-recovered"
        assert transport.offset == 4096
        assert restarted_repo.get(job_id).metadata["youtube_upload"]["state"] == "completed"
    finally:
        with repo._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM jobs WHERE job_id = %s", (job_id,))
