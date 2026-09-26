"""Encrypted Redis credential vault for multi-process OAuth deployments."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from uuid import uuid4

import redis
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .credential_vault import CredentialRef


class RedisCredentialVault:
    """Stores only AES-GCM ciphertext in Redis; the master key stays external."""

    def __init__(self, client: redis.Redis, master_key: bytes, prefix: str = "mashahid:credentials:") -> None:
        if len(master_key) != 32:
            raise ValueError("master_key must be exactly 32 bytes")
        if not prefix:
            raise ValueError("prefix is required")
        self._client = client
        self._aes = AESGCM(master_key)
        self._prefix = prefix

    def put(
        self, *, platform: str, account_id: str, access_token: str,
        scopes: tuple[str, ...] = (), expires_at: datetime | None = None,
        refresh_token: str | None = None,
    ) -> CredentialRef:
        if not platform.strip() or not account_id.strip() or not access_token:
            raise ValueError("platform, account_id and access_token are required")
        if expires_at is not None and expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        ref = CredentialRef(
            credential_id=f"cred_{uuid4().hex}", platform=platform.strip().lower(),
            account_id=account_id.strip(), scopes=tuple(sorted(set(scopes))),
            expires_at=expires_at, refreshable=bool(refresh_token),
        )
        nonce = __import__("secrets").token_bytes(12)
        plaintext = json.dumps(
            {"access": access_token, "refresh": refresh_token}, separators=(",", ":")
        ).encode()
        ciphertext = self._aes.encrypt(nonce, plaintext, ref.credential_id.encode())
        payload = {
            "platform": ref.platform, "account_id": ref.account_id,
            "scopes": list(ref.scopes),
            "expires_at": ref.expires_at.isoformat() if ref.expires_at else None,
            "refreshable": ref.refreshable,
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }
        self._client.set(self._prefix + ref.credential_id, json.dumps(payload, separators=(",", ":")))
        return ref

    def get_secret(self, credential: CredentialRef) -> tuple[str, str | None]:
        raw = self._client.get(self._prefix + credential.credential_id)
        if raw is None:
            raise KeyError("unknown credential reference")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        stored = CredentialRef(
            credential_id=credential.credential_id, platform=data["platform"],
            account_id=data["account_id"], scopes=tuple(data["scopes"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data["expires_at"] else None,
            refreshable=bool(data["refreshable"]),
        )
        if stored != credential:
            raise KeyError("credential reference metadata mismatch")
        if credential.expires_at is not None and credential.expires_at <= datetime.now(timezone.utc):
            raise PermissionError("credential is expired")
        try:
            plaintext = self._aes.decrypt(
                base64.b64decode(data["nonce"]), base64.b64decode(data["ciphertext"]),
                credential.credential_id.encode(),
            )
            body = json.loads(plaintext)
        except Exception as exc:
            raise PermissionError("credential ciphertext could not be authenticated") from exc
        return body["access"], body.get("refresh")

    def delete(self, credential: CredentialRef) -> None:
        self._client.delete(self._prefix + credential.credential_id)
