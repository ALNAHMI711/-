from datetime import datetime, timezone

import httpx
import pytest

from app.oauth_token_exchange import (
    OAuthClientCredentials,
    OAuthTokenExchangeError,
    exchange_authorization_code,
)


class FakeTransport:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.url = None
        self.data = None
        self.timeout = None

    def post(self, url: str, *, data, timeout: float) -> httpx.Response:
        self.url = url
        self.data = dict(data)
        self.timeout = timeout
        return self.response


def credentials() -> OAuthClientCredentials:
    return OAuthClientCredentials("client-id", "client-secret")


def test_google_code_exchange_returns_opaque_bundle_without_logging_secrets():
    transport = FakeTransport(
        httpx.Response(
            200,
            json={
                "access_token": "access-secret",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "refresh-secret",
                "scope": "scope.one scope.two",
            },
        )
    )
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)

    result = exchange_authorization_code(
        "youtube",
        credentials(),
        "one-time-code",
        "https://app.example/callback",
        transport=transport,
        now=now,
    )

    assert transport.url == "https://oauth2.googleapis.com/token"
    assert transport.data["client_secret"] == "client-secret"
    assert result.access_token == "access-secret"
    assert result.refresh_token == "refresh-secret"
    assert result.expires_at == datetime(2026, 9, 16, 1, tzinfo=timezone.utc)
    assert result.scope == ("scope.one", "scope.two")


def test_tiktok_uses_client_key_parameter():
    transport = FakeTransport(httpx.Response(200, json={"access_token": "a", "token_type": "Bearer", "open_id": "u"}))

    result = exchange_authorization_code(
        "tiktok", credentials(), "code", "https://app.example/callback", transport=transport
    )

    assert result.provider_subject == "u"
    assert transport.url == "https://open.tiktokapis.com/v2/oauth/token/"
    assert transport.data["client_key"] == "client-id"
    assert "client_id" not in transport.data


def test_provider_failure_does_not_expose_response_body():
    transport = FakeTransport(httpx.Response(400, json={"error": "invalid_client", "secret": "do-not-leak"}))

    with pytest.raises(OAuthTokenExchangeError, match="provider rejected authorization code") as exc:
        exchange_authorization_code(
            "linkedin", credentials(), "code", "https://app.example/callback", transport=transport
        )

    assert "do-not-leak" not in str(exc.value)


def test_unknown_platform_and_missing_credentials_are_rejected():
    with pytest.raises(OAuthTokenExchangeError):
        exchange_authorization_code("unknown", credentials(), "code", "https://app.example/callback")
    with pytest.raises(OAuthTokenExchangeError):
        exchange_authorization_code(
            "youtube", OAuthClientCredentials("", "secret"), "code", "https://app.example/callback"
        )
