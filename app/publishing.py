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


class PublishingError(RuntimeError):
    pass


class UnsupportedPublishing(PublishingError):
    pass


class PublishingService:
    def __init__(self, publishers: Mapping[str, Publisher], account_repository, credential_vault) -> None:
        self._publishers = dict(publishers)
        self._accounts = account_repository
        self._vault = credential_vault

    def publish(self, request: PublishRequest) -> PublishResult:
        if not request.project_id.strip() or not request.account_id.strip():
            raise ValueError("project_id and account_id are required")
        if not request.text.strip() and not request.media_url:
            raise ValueError("text or media_url is required")
        account = self._accounts.get(request.project_id, request.account_id)
        if account is None:
            raise PublishingError("account is not linked to this project")
        if not account.ready_to_publish:
            raise PublishingError("account is not verified and ready to publish")
        publisher = self._publishers.get(request.platform)
        if publisher is None:
            raise UnsupportedPublishing(f"official publisher is not configured: {request.platform}")
        if publisher.platform != request.platform:
            raise PublishingError("publisher/platform mismatch")
        credential = self._vault.find_for_account(request.platform, request.account_id)
        if credential is None:
            raise PublishingError("credential is not available")
        access_token, _ = self._vault.get_secret(credential)
        return publisher.publish(request, access_token)


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
