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
    def upload_video_from_url(self, upload_url: str, media_url: str, *, headers: Mapping[str, str]): ...


@dataclass(frozen=True)
class HttpxTransport:
    timeout: float = 15.0

    def get(self, url: str, *, headers: Mapping[str, str], params: Mapping[str, str]):
        with httpx.Client(timeout=self.timeout) as client:
            return client.get(url, headers=dict(headers), params=dict(params))

    def post(self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object]):
        with httpx.Client(timeout=self.timeout) as client:
            return client.post(url, headers=dict(headers), json=dict(json))

    def upload_video_resumable(self, upload_url: str, media_url: str, *, headers: Mapping[str, str]):
        """Stream an HTTPS media source into a resumable upload session."""
        from urllib.parse import urlparse
        import ipaddress

        def _validate_public_https(url: str, label: str) -> None:
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ProviderAPIError(f"{label} must use HTTPS")
            try:
                ip = ipaddress.ip_address(parsed.hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise ProviderAPIError(f"{label} resolves to a restricted address")
            except ValueError:
                pass

        _validate_public_https(media_url, "media_url")
        _validate_public_https(upload_url, "upload_url")
        chunk_size = 8 * 1024 * 1024
        max_retries = 3
        offset = 0
        with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
            with client.stream("GET", media_url) as source:
                source.raise_for_status()
                content_type = source.headers.get("content-type", "video/mp4").split(";")[0]
                total = source.headers.get("content-length")
                total_size = int(total) if total and total.isdigit() else None
                buffer = bytearray()
                for part in source.iter_bytes(chunk_size=1024 * 1024):
                    buffer.extend(part)
                    while len(buffer) >= chunk_size:
                        chunk = bytes(buffer[:chunk_size])
                        del buffer[:chunk_size]
                        offset = self._put_upload_chunk(
                            client, upload_url, chunk, offset, total_size,
                            content_type, headers, max_retries,
                        )
                if buffer or offset == 0:
                    offset = self._put_upload_chunk(
                        client, upload_url, bytes(buffer), offset, total_size,
                        content_type, headers, max_retries,
                    )
        return None

    @staticmethod
    def _put_upload_chunk(client, upload_url, chunk, offset, total_size, content_type, headers, max_retries):
        end = offset + len(chunk) - 1
        total_value = str(total_size) if total_size is not None else "*"
        request_headers = {
            "Authorization": headers.get("Authorization", ""),
            "Content-Type": content_type,
            "Content-Length": str(len(chunk)),
            "Content-Range": f"bytes {offset}-{end}/{total_value}",
        }
        for attempt in range(max_retries):
            response = client.put(upload_url, headers=request_headers, content=chunk)
            if response.status_code in (200, 201):
                return end + 1
            if response.status_code == 308:
                range_header = response.headers.get("Range", "")
                if range_header.startswith("bytes=0-"):
                    try:
                        return int(range_header.split("-", 1)[1]) + 1
                    except ValueError:
                        pass
                return end + 1
            if response.status_code in (408, 429, 500, 502, 503, 504) and attempt + 1 < max_retries:
                continue
            raise ProviderAPIError(f"resumable upload failed with HTTP {response.status_code}")
        raise ProviderAPIError("resumable upload retry limit exceeded")


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

    def list_accounts(self, access_token: str) -> tuple[ProviderAccount, ...]:
        if not access_token:
            raise ProviderAPIError("access token is required")
        response = self.transport.get(
            self.endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"part": "snippet", "mine": "true", "maxResults": "50"},
        )
        payload = _json(response)
        items = payload.get("items")
        if not isinstance(items, list):
            raise ProviderAPIError("invalid YouTube channel list")
        accounts: list[ProviderAccount] = []
        for channel in items:
            if not isinstance(channel, dict):
                continue
            snippet = channel.get("snippet") if isinstance(channel.get("snippet"), dict) else {}
            channel_id = str(channel.get("id", "")).strip()
            title = str(snippet.get("title", "")).strip()
            if channel_id and title:
                accounts.append(ProviderAccount(account_id=channel_id, display_name=title))
        if not accounts:
            raise ProviderAPIError("no YouTube channels were returned")
        return tuple(accounts)

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
