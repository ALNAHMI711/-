"""Production OAuth composition from deployment environment.

Secrets are read only on the server. Missing configuration disables the
corresponding provider rather than falling back to insecure test credentials.
The current credential vault is encrypted process-memory storage; durable
production secret persistence must be supplied before multi-process rollout.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .credential_vault import EncryptedMemoryCredentialVault
from .oauth_token_exchange import (
    HttpxTokenExchangeTransport,
    OAuthClientCredentials,
    exchange_authorization_code,
)
from .provider_http import (
    HttpxTransport,
    LinkedInAccountProvider,
    TikTokAccountProvider,
    YouTubeAccountProvider,
)


@dataclass(frozen=True)
class RuntimeOAuth:
    exchangers: dict[str, object]
    providers: dict[str, object]
    credential_vault: EncryptedMemoryCredentialVault | None


class _ConfiguredExchanger:
    def __init__(self, platform: str, credentials: OAuthClientCredentials) -> None:
        self.platform = platform
        self.credentials = credentials
        self.transport = HttpxTokenExchangeTransport()

    def exchange_code(self, code: str, redirect_uri: str):
        return exchange_authorization_code(
            self.platform,
            self.credentials,
            code,
            redirect_uri,
            transport=self.transport,
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


def _vault() -> EncryptedMemoryCredentialVault | None:
    raw = os.getenv("CREDENTIAL_VAULT_MASTER_KEY", "").strip()
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        return None
    if len(key) != 32:
        return None
    return EncryptedMemoryCredentialVault(key)


def build_runtime_oauth() -> RuntimeOAuth:
    """Build configured provider adapters without exposing deployment secrets."""
    credentials = {
        "youtube": _credentials("YOUTUBE", secret_name="YOUTUBE_CLIENT_SECRET"),
        "tiktok": _tiktok_credentials(),
        "linkedin": _credentials("LINKEDIN", secret_name="LINKEDIN_CLIENT_SECRET"),
    }

    exchangers = {
        platform: _ConfiguredExchanger(platform, value)
        for platform, value in credentials.items()
        if value is not None
    }

    transport = HttpxTransport()
    providers: dict[str, object] = {}
    if "youtube" in exchangers:
        providers["youtube"] = YouTubeAccountProvider(transport)
    if "tiktok" in exchangers:
        providers["tiktok"] = TikTokAccountProvider(transport)
    if "linkedin" in exchangers:
        providers["linkedin"] = LinkedInAccountProvider(transport)

    return RuntimeOAuth(
        exchangers=exchangers,
        providers=providers,
        credential_vault=_vault(),
    )
