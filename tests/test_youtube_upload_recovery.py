from secrets import token_bytes

import pytest

from app.persistence import InMemoryJobRepository, StoredJob
from app.publishing import PublishRequest, PublicationState, PublishingError, YouTubeVideoPublisher


class Response:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body or {"id": "yt-final"}
        self.headers = headers or {}

    def json(self):
        return self._body


class InitTransport:
    def __init__(self):
        self.calls = []

    def post(self, url, *, headers, json):
        self.calls.append(("post", url, json))
        return Response(200, {}, {"location": "https://upload.example/session-1"})

    def upload_video_resumable(self, upload_url, media_url, *, headers, start_offset=0, on_progress=None):
        self.calls.append(("upload", upload_url, media_url, start_offset))
        if on_progress:
            on_progress(5)
        raise RuntimeError("simulated worker restart")


class ResumeTransport:
    def __init__(self):
        self.calls = []

    def post(self, url, *, headers, json):
        raise AssertionError("restart must reuse the durable upload session")

    def upload_video_resumable(self, upload_url, media_url, *, headers, start_offset=0, on_progress=None):
        self.calls.append((upload_url, media_url, start_offset))
        assert upload_url == "https://upload.example/session-1"
        assert media_url == "https://cdn.example/video.mp4"
        assert start_offset == 5
        if on_progress:
            on_progress(8)
        return Response(200, {"id": "yt-recovered"})


def _job(repo):
    return repo.create(StoredJob(
        job_id="pub_restart",
        job_type="publish",
        idempotency_key="idem-1",
        state="running",
        attempts=1,
        max_attempts=3,
    ))


def test_youtube_upload_session_survives_worker_restart_and_resumes():
    repo = InMemoryJobRepository()
    _job(repo)
    key = token_bytes(32)
    request = PublishRequest(
        "project-1", "channel-1", "youtube", "Video",
        media_url="https://cdn.example/video.mp4", job_id="pub_restart",
    )

    first = YouTubeVideoPublisher(InitTransport(), repo, key)
    with pytest.raises(RuntimeError, match="simulated worker restart"):
        first.publish(request, "access-token")

    stored = repo.get("pub_restart")
    session = stored.metadata["youtube_upload"]
    assert session["offset"] == 5
    assert session["state"] == "active"
    assert "https://upload.example/session-1" not in str(session["upload_url"])
    assert "media_url" not in session
    assert "https://cdn.example/video.mp4" not in str(session)

    second_transport = ResumeTransport()
    second = YouTubeVideoPublisher(second_transport, repo, key)
    result = second.publish(request, "access-token")

    assert result.state is PublicationState.PUBLISHED
    assert result.provider_post_id == "yt-recovered"
    assert second_transport.calls == [
        ("https://upload.example/session-1", "https://cdn.example/video.mp4", 5)
    ]
    assert repo.get("pub_restart").metadata["youtube_upload"]["state"] == "completed"


def test_youtube_upload_session_is_project_and_account_bound():
    repo = InMemoryJobRepository()
    _job(repo)
    key = token_bytes(32)
    request = PublishRequest(
        "project-1", "channel-1", "youtube", "Video",
        media_url="https://cdn.example/video.mp4", job_id="pub_restart",
    )
    publisher = YouTubeVideoPublisher(InitTransport(), repo, key)
    with pytest.raises(RuntimeError):
        publisher.publish(request, "access-token")

    wrong = PublishRequest(
        "project-2", "channel-1", "youtube", "Video",
        media_url="https://cdn.example/video.mp4", job_id="pub_restart",
    )
    with pytest.raises(PublishingError, match="project/account"):
        YouTubeVideoPublisher(ResumeTransport(), repo, key).publish(wrong, "access-token")


def test_youtube_upload_session_requires_a_32_byte_key():
    repo = InMemoryJobRepository()
    _job(repo)
    with pytest.raises(ValueError, match="32 bytes"):
        YouTubeVideoPublisher(ResumeTransport(), repo, b"short")
