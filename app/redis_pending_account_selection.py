"""Redis-backed, single-use pending OAuth account selection storage."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from secrets import token_urlsafe

import redis

from .account_provider import ProviderAccount
from .credential_vault import CredentialRef
from .pending_account_selection import PendingAccountSelection


class RedisPendingAccountSelectionStore:
    """Durable short-lived selection state shared by app processes."""

    def __init__(self, client: redis.Redis, ttl_seconds: int = 600, prefix: str = "mashahid:oauth-selection:") -> None:
        if ttl_seconds <= 0 or not prefix:
            raise ValueError("valid ttl_seconds and prefix are required")
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._prefix = prefix

    def create(
        self, *, user_id: str, project_id: str, platform: str,
        credential: CredentialRef, accounts: tuple[ProviderAccount, ...],
        now: datetime | None = None,
    ) -> PendingAccountSelection:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        token = token_urlsafe(32)
        expires_at = current.timestamp() + self._ttl_seconds
        item = PendingAccountSelection(
            selection_token=token, user_id=user_id, project_id=project_id,
            platform=platform, credential=credential, accounts=accounts,
            expires_at=datetime.fromtimestamp(expires_at, timezone.utc),
        )
        payload = {
            "user_id": item.user_id, "project_id": item.project_id,
            "platform": item.platform,
            "credential": {
                "credential_id": credential.credential_id,
                "platform": credential.platform,
                "account_id": credential.account_id,
                "scopes": list(credential.scopes),
                "expires_at": credential.expires_at.isoformat() if credential.expires_at else None,
                "refreshable": credential.refreshable,
            },
            "accounts": [{"account_id": a.account_id, "display_name": a.display_name, "permissions": list(a.permissions)}
                         for a in accounts],
            "expires_at": item.expires_at.isoformat(),
        }
        self._client.set(self._prefix + token, json.dumps(payload, separators=(",", ":")), ex=self._ttl_seconds)
        return item

    def consume(
        self, selection_token: str, *, user_id: str, project_id: str,
        account_id: str, now: datetime | None = None,
    ) -> PendingAccountSelection:
        key = self._prefix + selection_token
        raw = self._client.get(key)
        if raw is None:
            raise ValueError("selection token is invalid or expired")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        expires_at = datetime.fromisoformat(data["expires_at"])
        if expires_at <= current:
            self._client.delete(key)
            raise ValueError("selection token is expired")
        if data["user_id"] != user_id or data["project_id"] != project_id:
            raise ValueError("selection token does not belong to this user/project")
        accounts = tuple(
            ProviderAccount(
                account_id=a["account_id"], display_name=a["display_name"],
                permissions=tuple(a.get("permissions", ())),
            ) for a in data["accounts"]
        )
        if account_id not in {a.account_id for a in accounts}:
            raise ValueError("selected account was not offered by the provider")
        c = data["credential"]
        credential = CredentialRef(
            credential_id=c["credential_id"], platform=c["platform"],
            account_id=c["account_id"], scopes=tuple(c["scopes"]),
            expires_at=datetime.fromisoformat(c["expires_at"]) if c["expires_at"] else None,
            refreshable=bool(c["refreshable"]),
        )
        # WATCH/MULTI would be required for a fully general atomic check-and-delete.
        # A Lua script keeps the consume operation single-use and race-safe.
        deleted = self._client.eval(
            "local v=redis.call('GET',KEYS[1]); if not v then return 0 end; if v~=ARGV[1] then return 0 end; redis.call('DEL',KEYS[1]); return 1",
            1, key, raw,
        )
        if not deleted:
            raise ValueError("selection token is invalid or already consumed")
        return PendingAccountSelection(
            selection_token=selection_token, user_id=data["user_id"],
            project_id=data["project_id"], platform=data["platform"],
            credential=credential, accounts=accounts, expires_at=expires_at,
        )

    def purge_expired(self, now: datetime | None = None) -> int:
        return 0
