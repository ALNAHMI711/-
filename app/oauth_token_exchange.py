"""Server-side OAuth authorization-code exchange primitives.

Provider secrets and issued tokens never belong in API payloads or domain models.
The exchange client returns an opaque token bundle to the caller so a credential
vault can persist it without exposing values through logs or serialization.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Protocol

import httpx


@dataclass(frozen=True)
class OAuthClientCredentials:
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class OAuthTokenBundle:
    access_token: str
    token_type: str
    expires_at: datetime | None
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None
    scope: tuple[str, ...] = ()
    provider_subject: str | None = None

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise ValueError("access_token is required")
        if not self.token_type.strip():
            raise ValueError("token_type is required")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        if self.refresh_expires_at is not None and self.refresh_expires_at.tzinfo is None:
            raise ValueError("refresh_expires_at must be timezone-aware")


class OAuthTokenExchangeError(RuntimeError):
    """Raised when a provider rejects or returns an invalid token exchange."""


class TokenExchangeTransport(Protocol):
    def post(self, url: str, *, data: Mapping[str, str], timeout: float) -> httpx.Response: ...


class HttpxTokenExchangeTransport:
    def post(self, url: str, *, data: Mapping[str, str], timeout: float) -> httpx.Response:
        with httpx.Client(follow_redirects=False) as client:
            return client.post(url, data=data, timeout=timeout)


_TOKEN_ENDPOINTS = {
    "youtube": "https://oauth2.googleapis.com/token",
    "tiktok": "https://open.tiktokapis.com/v2/oauth/token/",
    "linkedin": "https://www.linkedin.com/oauth/v2/accessToken",
}


def _expires_at(seconds: object, now: datetime) -> datetime | None:
    if seconds in (None, ""):
        return None
    try:
        value = int(seconds)
    except (TypeError, ValueError) as exc:
        raise OAuthTokenExchangeError("provider returned invalid expires_in") from exc
    if value < 0:
        raise OAuthTokenExchangeError("provider returned invalid expires_in")
    return now + timedelta(seconds=value)


def _scope_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(part for part in value.replace(",", " ").split() if part)


def exchange_authorization_code(
    platform: str,
    credentials: OAuthClientCredentials,
    code: str,
    redirect_uri: str,
    *,
    transport: TokenExchangeTransport | None = None,
    now: datetime | None = None,
    timeout: float = 10.0,
) -> OAuthTokenBundle:
    """Exchange a short-lived authorization code using server-side credentials."""
    key = platform.strip().lower()
    endpoint = _TOKEN_ENDPOINTS.get(key)
    if endpoint is None:
        raise OAuthTokenExchangeError(f"unsupported OAuth token exchange platform: {platform}")
    if not credentials.client_id.strip() or not credentials.client_secret.strip():
        raise OAuthTokenExchangeError("OAuth client credentials are not configured")
    if not code.strip():
        raise OAuthTokenExchangeError("authorization code is required")
    if not redirect_uri.strip():
        raise OAuthTokenExchangeError("redirect_uri is required")
    if timeout <= 0 or timeout > 30:
        raise OAuthTokenExchangeError("timeout must be between 0 and 30 seconds")

    now_value = now or datetime.now(timezone.utc)
    if now_value.tzinfo is None:
        raise OAuthTokenExchangeError("now must be timezone-aware")

    data: dict[str, str] = {
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if key == "tiktok":
        data["client_key"] = data.pop("client_id")
    response = (transport or HttpxTokenExchangeTransport()).post(endpoint, data=data, timeout=timeout)
    try:
        payload = response.json()
    except ValueError as exc:
        raise OAuthTokenExchangeError("provider returned invalid JSON") from exc
    if not response.is_success:
        raise OAuthTokenExchangeError("provider rejected authorization code")
    if not isinstance(payload, dict):
        raise OAuthTokenExchangeError("provider returned invalid token payload")

    access_token = payload.get("access_token")
    token_type = payload.get("token_type", "Bearer")
    if not isinstance(access_token, str) or not access_token.strip():
        raise OAuthTokenExchangeError("provider did not return an access token")
    if not isinstance(token_type, str) or not token_type.strip():
        raise OAuthTokenExchangeError("provider returned invalid token_type")

    refresh_token = payload.get("refresh_token")
    if refresh_token is not None and not isinstance(refresh_token, str):
        raise OAuthTokenExchangeError("provider returned invalid refresh_token")

    expires = _expires_at(payload.get("expires_in"), now_value)
    refresh_expires = _expires_at(
        payload.get("refresh_expires_in", payload.get("refresh_token_expires_in")), now_value
    )
    subject = payload.get("open_id") if key == "tiktok" else None
    return OAuthTokenBundle(
        access_token=access_token,
        token_type=token_type,
        expires_at=expires,
        refresh_token=refresh_token,
        refresh_expires_at=refresh_expires,
        scope=_scope_tuple(payload.get("scope")),
        provider_subject=subject if isinstance(subject, str) else None,
    )
