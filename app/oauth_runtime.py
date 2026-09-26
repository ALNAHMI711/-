"""Production OAuth composition from deployment environment.

OAuth state, pending selections, and credentials use Redis in production when
REDIS_URL and a valid credential master key are configured. The master key is
never persisted by the application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import redis

from .credential_vault import EncryptedMemoryCredentialVault
from .oauth_token_exchange import (
    HttpxTokenExchangeTransport,
    OAuthClientCredentials,
    exchange_authorization_code,
)
from .provider_http import (
    HttpxTransport, LinkedInAccountProvider, TikTokAccountProvider, YouTubeAccountProvider,
)
from .redis_credential_vault import RedisCredentialVault


@dataclass(frozen=True)
class RuntimeOAuth:
    exchangers: dict[str, object]
    providers: dict[str, object]
    credential_vault: object | None


class _ConfiguredExchanger:
    def __init__(self, platform: str, credentials: OAuthClientCredentials) -> None:
        self.platform = platform
        self.credentials = credentials
        self.transport = HttpxTokenExchangeTransport()

    def exchange_code(self, code: str, redirect_uri: str):
        return exchange_authorization_code(
            self.platform, self.credentials, code, redirect_uri, transport=self.transport,
        )


def _credentials(prefix: str, *, secret_name: str) -> OAuthClientCredentials | None:
    client_id = os.getenv(f"{prefix}_CLIENT_ID", "").strip()
    client_secret = os.getenv(secret_name, "").strip()
    if not client_id or not client_secret:
        return None
    return OAuthClientCredentials(client_id=client_id, client_secret=client_secret)


def _tiktok_credentials() -> OAuthClientCredentials | None:
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    if not client_key or not client_secret:
        return None
    return OAuthClientCredentials(client_id=client_key, client_secret=client_secret)


def _master_key() -> bytes | None:
    raw = os.getenv("CREDENTIAL_VAULT_MASTER_KEY", "").strip()
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        return None
    return key if len(key) == 32 else None


def _vault():
    key = _master_key()
    if key is None:
        return None
    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        return RedisCredentialVault(redis.from_url(redis_url), key)
    return EncryptedMemoryCredentialVault(key)


def build_runtime_oauth() -> RuntimeOAuth:
    credentials = {
        "youtube": _credentials("YOUTUBE", secret_name="YOUTUBE_CLIENT_SECRET"),
        "tiktok": _tiktok_credentials(),
        "linkedin": _credentials("LINKEDIN", secret_name="LINKEDIN_CLIENT_SECRET"),
    }
    exchangers = {
        platform: _ConfiguredExchanger(platform, value)
        for platform, value in credentials.items() if value is not None
    }
    transport = HttpxTransport()
    providers: dict[str, object] = {}
    if "youtube" in exchangers:
        providers["youtube"] = YouTubeAccountProvider(transport)
    if "tiktok" in exchangers:
        providers["tiktok"] = TikTokAccountProvider(transport)
    if "linkedin" in exchangers:
        providers["linkedin"] = LinkedInAccountProvider(transport)
    return RuntimeOAuth(exchangers=exchangers, providers=providers, credential_vault=_vault())
