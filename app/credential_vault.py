"""Secure credential storage contracts for OAuth provider credentials."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class CredentialRef:
    credential_id: str
    platform: str
    account_id: str
    scopes: tuple[str, ...]
    expires_at: datetime | None = None
    refreshable: bool = False


class CredentialVault(Protocol):
    def put(self, *, platform: str, account_id: str, access_token: str,
            scopes: tuple[str, ...] = (), expires_at: datetime | None = None,
            refresh_token: str | None = None) -> CredentialRef: ...
    def get_secret(self, credential: CredentialRef) -> tuple[str, str | None]: ...
    def find_for_account(self, platform: str, account_id: str) -> CredentialRef | None: ...
    def delete(self, credential: CredentialRef) -> None: ...


class InMemoryCredentialVault:
    def __init__(self) -> None:
        self._secrets: dict[str, tuple[str, str | None]] = {}
        self._refs: dict[str, CredentialRef] = {}

    def put(self, *, platform: str, account_id: str, access_token: str,
            scopes: tuple[str, ...] = (), expires_at: datetime | None = None,
            refresh_token: str | None = None) -> CredentialRef:
        if not platform.strip() or not account_id.strip() or not access_token:
            raise ValueError("platform, account_id and access_token are required")
        if expires_at is not None and expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        ref = CredentialRef(
            f"cred_{uuid4().hex}", platform.strip().lower(), account_id.strip(),
            tuple(sorted(set(scopes))), expires_at, bool(refresh_token)
        )
        self._refs[ref.credential_id] = ref
        self._secrets[ref.credential_id] = (access_token, refresh_token)
        return ref

    def find_for_account(self, platform: str, account_id: str) -> CredentialRef | None:
        for ref in self._refs.values():
            if ref.platform == platform.strip().lower() and ref.account_id == account_id.strip():
                return ref
        return None

    def get_secret(self, credential: CredentialRef) -> tuple[str, str | None]:
        stored = self._refs.get(credential.credential_id)
        if stored != credential:
            raise KeyError("unknown credential reference")
        if credential.expires_at is not None and credential.expires_at <= datetime.now(timezone.utc):
            raise PermissionError("credential is expired")
        return self._secrets[credential.credential_id]

    def delete(self, credential: CredentialRef) -> None:
        self._refs.pop(credential.credential_id, None)
        self._secrets.pop(credential.credential_id, None)


class EncryptedMemoryCredentialVault(InMemoryCredentialVault):
    """Development/test vault with authenticated encryption semantics.

    The master key is external and this store is process-local.
    """

    def __init__(self, master_key: bytes) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if len(master_key) not in {16, 24, 32}:
            raise ValueError("master_key must be 128, 192 or 256 bits")
        self._aes = AESGCM(master_key)
        self._records: dict[str, tuple[CredentialRef, bytes, bytes]] = {}

    def put(self, *, platform: str, account_id: str, access_token: str,
            scopes: tuple[str, ...] = (), expires_at: datetime | None = None,
            refresh_token: str | None = None) -> CredentialRef:
        if not platform.strip() or not account_id.strip() or not access_token:
            raise ValueError("platform, account_id and access_token are required")
        from secrets import token_bytes
        ref = CredentialRef(
            f"cred_{uuid4().hex}", platform.strip().lower(), account_id.strip(),
            tuple(sorted(set(scopes))), expires_at, bool(refresh_token)
        )
        nonce = token_bytes(12)
        plaintext = (access_token + "\x00" + (refresh_token or "")).encode()
        self._records[ref.credential_id] = (ref, nonce, self._aes.encrypt(nonce, plaintext, ref.credential_id.encode()))
        return ref

    def find_for_account(self, platform: str, account_id: str) -> CredentialRef | None:
        platform = platform.strip().lower()
        for ref, _, _ in self._records.values():
            if ref.platform == platform and ref.account_id == account_id.strip():
                return ref
        return None

    def get_secret(self, credential: CredentialRef) -> tuple[str, str | None]:
        stored = self._records.get(credential.credential_id)
        if stored is None or stored[0] != credential:
            raise KeyError("unknown credential reference")
        if credential.expires_at is not None and credential.expires_at <= datetime.now(timezone.utc):
            raise PermissionError("credential is expired")
        access, _, refresh = self._aes.decrypt(stored[1], stored[2], credential.credential_id.encode()).decode().partition("\x00")
        return access, refresh or None

    def delete(self, credential: CredentialRef) -> None:
        self._records.pop(credential.credential_id, None)
