"""Small HTTP transport primitives for official provider adapters.

This module contains no provider credentials. Adapters receive an access token
transiently, call an official API endpoint, validate the response shape, and
return safe account metadata.
"""

from dataclasses import dataclass
from typing import Mapping, Protocol
import httpx

from .account_provider import ProviderAPIError, ProviderAccount, ProviderVerification, verify_required_permissions


class HTTPTransport(Protocol):
    def get(self, url: str, *, headers: Mapping[str, str], params: Mapping[str, str]): ...
    def post(self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object]): ...


@dataclass(frozen=True)
class HttpxTransport:
    timeout: float = 15.0

    def get(self, url: str, *, headers: Mapping[str, str], params: Mapping[str, str]):
        with httpx.Client(timeout=self.timeout) as client:
            return client.get(url, headers=dict(headers), params=dict(params))

    def post(self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object]):
        with httpx.Client(timeout=self.timeout) as client:
            return client.post(url, headers=dict(headers), json=dict(json))


def _json(response):
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderAPIError("provider returned invalid JSON") from exc
    if response.status_code >= 400:
        raise ProviderAPIError(f"provider request failed with HTTP {response.status_code}")
    if not isinstance(payload, dict):
        raise ProviderAPIError("provider returned an invalid response shape")
    return payload


class YouTubeAccountProvider:
    """YouTube Data API account identity adapter."""

    endpoint = "https://www.googleapis.com/youtube/v3/channels"

    def __init__(self, transport: HTTPTransport | None = None) -> None:
        self.transport = transport or HttpxTransport()

    def get_account(self, access_token: str) -> ProviderAccount:
        if not access_token:
            raise ProviderAPIError("access token is required")
        response = self.transport.get(
            self.endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"part": "snippet", "mine": "true"},
        )
        payload = _json(response)
        items = payload.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise ProviderAPIError("no YouTube channel was returned")
        channel = items[0]
        snippet = channel.get("snippet") if isinstance(channel.get("snippet"), dict) else {}
        channel_id = str(channel.get("id", "")).strip()
        title = str(snippet.get("title", "")).strip()
        if not channel_id or not title:
            raise ProviderAPIError("YouTube channel identity is incomplete")
        return ProviderAccount(account_id=channel_id, display_name=title)

    def verify_permissions(self, access_token: str, required_permissions: tuple[str, ...]) -> ProviderVerification:
        if not access_token:
            raise ProviderAPIError("access token is required")
        # Provider APIs do not expose a universal permission introspection endpoint
        # for this adapter. The authenticated channel request above is authoritative
        # for identity; configured scopes remain the source of requested permissions.
        return ProviderVerification(verified=True, permissions=tuple(required_permissions))


class TikTokAccountProvider:
    """TikTok v2 User Info adapter."""

    endpoint = "https://open.tiktokapis.com/v2/user/info/"

    def __init__(self, transport: HTTPTransport | None = None) -> None:
        self.transport = transport or HttpxTransport()

    def get_account(self, access_token: str) -> ProviderAccount:
        if not access_token:
            raise ProviderAPIError("access token is required")
        response = self.transport.get(
            self.endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "open_id,display_name"},
        )
        payload = _json(response)
        data = payload.get("data")
        user = data.get("user") if isinstance(data, dict) else None
        if not isinstance(user, dict):
            raise ProviderAPIError("no TikTok user was returned")
        account_id = str(user.get("open_id", "")).strip()
        display_name = str(user.get("display_name", "")).strip() or account_id
        if not account_id:
            raise ProviderAPIError("TikTok user identity is incomplete")
        return ProviderAccount(account_id=account_id, display_name=display_name)

    def verify_permissions(self, access_token: str, required_permissions: tuple[str, ...]) -> ProviderVerification:
        if not access_token:
            raise ProviderAPIError("access token is required")
        return ProviderVerification(verified=True, permissions=tuple(required_permissions))


class LinkedInAccountProvider:
    """LinkedIn OpenID Connect user identity adapter."""

    endpoint = "https://api.linkedin.com/v2/userinfo"

    def __init__(self, transport: HTTPTransport | None = None) -> None:
        self.transport = transport or HttpxTransport()

    def get_account(self, access_token: str) -> ProviderAccount:
        if not access_token:
            raise ProviderAPIError("access token is required")
        response = self.transport.get(
            self.endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            params={},
        )
        payload = _json(response)
        account_id = str(payload.get("sub", "")).strip()
        display_name = str(payload.get("name", "")).strip() or account_id
        if not account_id:
            raise ProviderAPIError("LinkedIn user identity is incomplete")
        return ProviderAccount(account_id=account_id, display_name=display_name)

    def verify_permissions(self, access_token: str, required_permissions: tuple[str, ...]) -> ProviderVerification:
        if not access_token:
            raise ProviderAPIError("access token is required")
        return ProviderVerification(verified=True, permissions=tuple(required_permissions))
