from datetime import datetime, timezone

import pytest

from app.account_connections import AccountConnection, ConnectionState, MonetizationState, VerificationState
from app.audit_log import AuditEvent, InMemoryAuditLog
from app.publishing import (
    LinkedInTextPublisher, PublishRequest, PublicationState,
    PublishingError, PublishingService, TikTokDirectPublisher, UnsupportedPublishing,
    YouTubeVideoPublisher, build_official_publishers,
)


class FakeResponse:
    status_code = 201
    headers = {"x-restli-id": "urn:li:share:123"}

    def __init__(self, body=None, status_code=201, headers=None):
        self._body = body or {}
        self.status_code = status_code
        self.headers = headers or {"x-restli-id": "urn:li:share:123"}

    def json(self):
        return self._body


class FakeTransport:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or FakeResponse()

    def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        return self.response


class FakeVault:
    def __init__(self, credential):
        self.credential = credential

    def find_for_account(self, platform, account_id):
        return self.credential if platform == self.credential.platform and account_id == self.credential.account_id else None

    def get_secret(self, credential):
        return ("access-token", None)


class FakeAccounts:
    def __init__(self, account):
        self.account = account

    def get(self, project_id, account_id):
        return self.account if self.account.project_id == project_id and self.account.account_id == account_id else None


def account():
    return AccountConnection(
        account_id="member-1", platform="linkedin", display_name="Member",
        project_id="project-1", connection_state=ConnectionState.CONNECTED,
        verification_state=VerificationState.VERIFIED,
        monetization_state=MonetizationState.UNKNOWN, permissions=("w_member_social",),
    )


def credential():
    from app.credential_vault import CredentialRef
    return CredentialRef("cred-1", "linkedin", "member-1", ("w_member_social",), None, False)


def test_linkedin_text_publish_uses_official_response():
    transport = FakeTransport()
    publisher = LinkedInTextPublisher(transport)
    result = publisher.publish(
        PublishRequest("project-1", "member-1", "linkedin", "hello"),
        "access-token",
    )
    assert result.state is PublicationState.PUBLISHED
    assert result.provider_post_id == "urn:li:share:123"
    assert transport.calls[0][1]["Authorization"] == "Bearer access-token"


def test_service_enforces_project_and_readiness():
    service = PublishingService(
        {"linkedin": LinkedInTextPublisher(FakeTransport())},
        FakeAccounts(account()), FakeVault(credential()),
    )
    result = service.publish(PublishRequest("project-1", "member-1", "linkedin", "hello"))
    assert result.state is PublicationState.PUBLISHED


def test_service_rejects_unverified_account():
    bad = account()
    bad = AccountConnection(
        **{**bad.__dict__, "verification_state": VerificationState.ACTION_REQUIRED}
    )
    service = PublishingService(
        {"linkedin": LinkedInTextPublisher(FakeTransport())},
        FakeAccounts(bad), FakeVault(credential()),
    )
    with pytest.raises(PublishingError):
        service.publish(PublishRequest("project-1", "member-1", "linkedin", "hello"))


def test_media_is_not_claimed_as_published():
    publisher = LinkedInTextPublisher(FakeTransport())
    with pytest.raises(UnsupportedPublishing):
        publisher.publish(
            PublishRequest("project-1", "member-1", "linkedin", "caption", media_url="https://example.com/video.mp4"),
            "access-token",
        )


def test_tiktok_direct_post_uses_official_api_and_stays_pending():
    response = FakeResponse({"data": {"publish_id": "v_pub_123"}, "error": {"code": "ok", "message": ""}})
    transport = FakeTransport(response)
    publisher = TikTokDirectPublisher(transport)
    result = publisher.publish(
        PublishRequest("project-1", "tiktok-user", "tiktok", "caption", media_url="https://cdn.example/video.mp4"),
        "access-token",
    )
    assert result.state is PublicationState.PUBLISHING
    assert result.provider_post_id == "v_pub_123"


def test_tiktok_status_processing_remains_pending():
    response = FakeResponse({"data": {"status": "PROCESSING_DOWNLOAD"}, "error": {"code": "ok", "message": ""}})
    transport = FakeTransport(response)
    publisher = TikTokDirectPublisher(transport)
    result = publisher.check_status("v_pub_123", "access-token")
    assert result.state is PublicationState.PUBLISHING
    assert result.provider_post_id == "v_pub_123"
    assert transport.calls[0][0].endswith("/v2/post/publish/status/fetch/")
    assert transport.calls[0][2] == {"publish_id": "v_pub_123"}


def test_tiktok_status_confirms_publication():
    response = FakeResponse({
        "data": {
            "status": "PUBLISH_COMPLETE",
            "publicaly_available_post_id": ["987654321"],
        },
        "error": {"code": "ok", "message": ""},
    })
    publisher = TikTokDirectPublisher(FakeTransport(response))
    result = publisher.check_status("v_pub_123", "access-token")
    assert result.state is PublicationState.PUBLISHED
    assert result.provider_post_id == "987654321"
    assert result.published_at is not None


def test_tiktok_status_reports_failure():
    response = FakeResponse({
        "data": {"status": "FAILED", "fail_reason": "duration_check_failed"},
        "error": {"code": "ok", "message": ""},
    })
    publisher = TikTokDirectPublisher(FakeTransport(response))
    result = publisher.check_status("v_pub_123", "access-token")
    assert result.state is PublicationState.FAILED
    assert result.provider_post_id == "v_pub_123"
    assert "duration_check_failed" in result.detail


def test_tiktok_rejects_missing_publish_id():
    transport = FakeTransport(FakeResponse({"data": {}, "error": {"code": "ok", "message": ""}}))
    publisher = TikTokDirectPublisher(transport)
    with pytest.raises(PublishingError):
        publisher.publish(
            PublishRequest("project-1", "tiktok-user", "tiktok", "caption", media_url="https://cdn.example/video.mp4"),
            "access-token",
        )


def test_audit_log_contains_no_credentials():
    log = InMemoryAuditLog()
    log.append(AuditEvent("evt-1", "admin", "publish", "project-1", "member-1", "published", datetime.now(timezone.utc)))
    assert "access-token" not in str(log.list_for_project("project-1"))


class FakeYouTubeTransport:
    def __init__(self):
        self.calls = []
        self.init_response = FakeResponse({}, 200, {"location": "https://upload.example/session"})
        self.upload_response = FakeResponse({"id": "yt-video-123"}, 200, {})

    def post(self, url, *, headers, json):
        self.calls.append(("post", url, headers, json))
        return self.init_response

    def upload_video_resumable(self, upload_url, media_url, *, headers):
        self.calls.append(("upload_resumable", upload_url, media_url, headers))
        return self.upload_response


def test_official_publisher_registry_includes_youtube():
    registry = build_official_publishers(FakeYouTubeTransport())
    assert set(registry) == {"linkedin", "tiktok", "youtube"}
    assert registry["youtube"].platform == "youtube"



def youtube_account():
    return AccountConnection(
        account_id="channel-1", platform="youtube", display_name="Channel",
        project_id="project-1", connection_state=ConnectionState.CONNECTED,
        verification_state=VerificationState.VERIFIED,
        monetization_state=MonetizationState.UNKNOWN,
        permissions=("https://www.googleapis.com/auth/youtube.upload",),
    )


def youtube_credential():
    from app.credential_vault import CredentialRef
    return CredentialRef(
        "yt-cred-1", "youtube", "channel-1",
        ("https://www.googleapis.com/auth/youtube.upload",), None, False,
    )


def test_youtube_publishing_service_uses_registered_official_publisher():
    transport = FakeYouTubeTransport()
    service = PublishingService(
        build_official_publishers(transport),
        FakeAccounts(youtube_account()), FakeVault(youtube_credential()),
    )
    result = service.publish(PublishRequest(
        "project-1", "channel-1", "youtube", "My video",
        media_url="https://cdn.example/video.mp4",
    ))
    assert result.state is PublicationState.PUBLISHED
    assert result.provider_post_id == "yt-video-123"
    assert transport.calls[0][3]["status"]["privacyStatus"] == "private"

def test_youtube_video_publish_uses_resumable_upload_and_official_id():
    transport = FakeYouTubeTransport()
    publisher = YouTubeVideoPublisher(transport)
    result = publisher.publish(
        PublishRequest(
            "project-1", "channel-1", "youtube",
            "My video", media_url="https://cdn.example/video.mp4",
        ),
        "access-token",
    )
    assert result.state is PublicationState.PUBLISHED
    assert result.provider_post_id == "yt-video-123"
    assert result.provider_url.endswith("yt-video-123")
    assert transport.calls[0][1].startswith("https://www.googleapis.com/upload/youtube/v3/videos")
    assert transport.calls[1][0] == "upload_resumable"
    assert transport.calls[1][1] == "https://upload.example/session"


def test_youtube_rejects_missing_upload_session():
    transport = FakeYouTubeTransport()
    transport.init_response = FakeResponse({}, 200, {})
    publisher = YouTubeVideoPublisher(transport)
    with pytest.raises(PublishingError):
        publisher.publish(
            PublishRequest("project-1", "channel-1", "youtube", "My video", "https://cdn.example/video.mp4"),
            "access-token",
        )
