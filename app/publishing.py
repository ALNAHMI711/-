"""Official-API publishing domain contracts.

Publishers receive short-lived credentials only at execution time. They must
never simulate engagement or report success without an authoritative provider
response.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Protocol


class PublicationState(str, Enum):
    REQUESTED = "requested"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass(frozen=True)
class PublishRequest:
    project_id: str
    account_id: str
    platform: str
    text: str
    media_url: str | None = None
    idempotency_key: str = ""


@dataclass(frozen=True)
class PublishResult:
    state: PublicationState
    provider_post_id: str | None = None
    provider_url: str | None = None
    detail: str = ""
    published_at: datetime | None = None


class Publisher(Protocol):
    platform: str

    def publish(self, request: PublishRequest, access_token: str) -> PublishResult: ...


class StatusPublisher(Publisher, Protocol):
    def check_status(self, provider_post_id: str, access_token: str) -> PublishResult: ...


class PublishingError(RuntimeError):
    pass


class UnsupportedPublishing(PublishingError):
    pass


class PublishingService:
    def __init__(self, publishers: Mapping[str, Publisher], account_repository, credential_vault) -> None:
        self._publishers = dict(publishers)
        self._accounts = account_repository
        self._vault = credential_vault

    def _authorized_publisher(self, project_id: str, account_id: str, platform: str):
        if not project_id.strip() or not account_id.strip() or not platform.strip():
            raise ValueError("project_id, account_id and platform are required")
        account = self._accounts.get(project_id, account_id)
        if account is None:
            raise PublishingError("account is not linked to this project")
        if not account.ready_to_publish:
            raise PublishingError("account is not verified and ready to publish")
        publisher = self._publishers.get(platform)
        if publisher is None:
            raise UnsupportedPublishing(f"official publisher is not configured: {platform}")
        if publisher.platform != platform:
            raise PublishingError("publisher/platform mismatch")
        credential = self._vault.find_for_account(platform, account_id)
        if credential is None:
            raise PublishingError("credential is not available")
        access_token, _ = self._vault.get_secret(credential)
        return publisher, access_token

    def publish(self, request: PublishRequest) -> PublishResult:
        if not request.text.strip() and not request.media_url:
            raise ValueError("text or media_url is required")
        publisher, access_token = self._authorized_publisher(
            request.project_id, request.account_id, request.platform
        )
        return publisher.publish(request, access_token)

    def check_status(self, project_id: str, account_id: str, platform: str, provider_post_id: str) -> PublishResult:
        if not provider_post_id.strip():
            raise ValueError("provider_post_id is required")
        publisher, access_token = self._authorized_publisher(project_id, account_id, platform)
        checker = getattr(publisher, "check_status", None)
        if not callable(checker):
            raise UnsupportedPublishing(f"official status checker is not configured: {platform}")
        return checker(provider_post_id, access_token)


@dataclass(frozen=True)
class LinkedInTextPublisher:
    """Minimal official LinkedIn member-post publisher."""

    platform: str = "linkedin"
    endpoint: str = "https://api.linkedin.com/v2/ugcPosts"

    def __init__(self, transport) -> None:
        object.__setattr__(self, "transport", transport)

    def publish(self, request: PublishRequest, access_token: str) -> PublishResult:
        if request.media_url:
            raise UnsupportedPublishing("LinkedIn media publishing requires an upload asset workflow")
        if not request.text.strip():
            raise ValueError("text is required")
        payload = {
            "author": request.account_id,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": request.text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        response = self.transport.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code >= 400:
            raise PublishingError(f"LinkedIn publish failed with HTTP {response.status_code}")
        post_id = str(response.headers.get("x-restli-id", "")).strip() or None
        return PublishResult(
            state=PublicationState.PUBLISHED,
            provider_post_id=post_id,
            detail="published by official LinkedIn API",
            published_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class TikTokDirectPublisher:
    """Official TikTok Content Posting API publisher using PULL_FROM_URL."""

    platform: str = "tiktok"
    endpoint: str = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    status_endpoint: str = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

    def __init__(self, transport) -> None:
        object.__setattr__(self, "transport", transport)

    def publish(self, request: PublishRequest, access_token: str) -> PublishResult:
        if not request.media_url:
            raise UnsupportedPublishing("TikTok Direct Post requires a video media_url")
        if not request.text.strip():
            raise ValueError("TikTok caption is required")
        payload = {
            "post_info": {
                "title": request.text,
                "privacy_level": "SELF_ONLY",
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": request.media_url,
            },
        }
        response = self.transport.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=payload,
        )
        if response.status_code >= 400:
            raise PublishingError(f"TikTok publish initialization failed with HTTP {response.status_code}")
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        publish_id = str(data.get("publish_id", "")).strip() if isinstance(data, dict) else ""
        if not publish_id:
            error = body.get("error") if isinstance(body, dict) else None
            detail = error.get("message", "TikTok returned no publish_id") if isinstance(error, dict) else "TikTok returned no publish_id"
            raise PublishingError(detail)
        return PublishResult(
            state=PublicationState.PUBLISHING,
            provider_post_id=publish_id,
            detail="accepted by official TikTok Content Posting API; awaiting status confirmation",
        )

    def check_status(self, publish_id: str, access_token: str) -> PublishResult:
        if not publish_id.strip():
            raise ValueError("publish_id is required")
        response = self.transport.post(
            self.status_endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id.strip()},
        )
        if response.status_code >= 400:
            raise PublishingError(f"TikTok status check failed with HTTP {response.status_code}")
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        status = str(data.get("status", "")).strip() if isinstance(data, dict) else ""
        if status == "PUBLISH_COMPLETE":
            ids = data.get("publicaly_available_post_id", [])
            post_id = str(ids[0]).strip() if isinstance(ids, list) and ids else publish_id
            return PublishResult(
                state=PublicationState.PUBLISHED,
                provider_post_id=post_id,
                detail="confirmed by official TikTok status API",
                published_at=datetime.now(timezone.utc),
            )
        if status == "FAILED":
            reason = str(data.get("fail_reason", "")).strip() if isinstance(data, dict) else ""
            return PublishResult(
                state=PublicationState.FAILED,
                provider_post_id=publish_id,
                detail=reason or "TikTok reported publishing failure",
            )
        if status in {"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD", "SEND_TO_USER_INBOX"}:
            return PublishResult(
                state=PublicationState.PUBLISHING,
                provider_post_id=publish_id,
                detail=f"TikTok status: {status}",
            )
        raise PublishingError(f"TikTok returned unknown publish status: {status or 'empty'}")


@dataclass(frozen=True)
class YouTubeVideoPublisher:
    """Official YouTube Data API resumable video publisher."""

    platform: str = "youtube"
    endpoint: str = "https://www.googleapis.com/upload/youtube/v3/videos?part=snippet,status&uploadType=resumable"

    def __init__(self, transport) -> None:
        object.__setattr__(self, "transport", transport)

    def publish(self, request: PublishRequest, access_token: str) -> PublishResult:
        if not request.media_url:
            raise UnsupportedPublishing("YouTube video publishing requires a media_url")
        if not request.text.strip():
            raise ValueError("YouTube title is required")
        metadata = {
            "snippet": {
                "title": request.text[:100],
                "description": request.text,
            },
            "status": {
                "privacyStatus": "private",
            },
        }
        response = self.transport.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/*",
            },
            json=metadata,
        )
        if response.status_code >= 400:
            raise PublishingError(f"YouTube upload initialization failed with HTTP {response.status_code}")
        upload_url = str(response.headers.get("location", "")).strip()
        if not upload_url:
            raise PublishingError("YouTube upload initialization returned no resumable upload URL")
        uploaded = self.transport.upload_video_from_url(
            upload_url,
            request.media_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if uploaded.status_code >= 400:
            raise PublishingError(f"YouTube video upload failed with HTTP {uploaded.status_code}")
        body = uploaded.json()
        video_id = str(body.get("id", "")).strip() if isinstance(body, dict) else ""
        if not video_id:
            raise PublishingError("YouTube upload returned no video id")
        return PublishResult(
            state=PublicationState.PUBLISHED,
            provider_post_id=video_id,
            provider_url=f"https://www.youtube.com/watch?v={video_id}",
            detail="published by official YouTube Data API",
            published_at=datetime.now(timezone.utc),
        )
