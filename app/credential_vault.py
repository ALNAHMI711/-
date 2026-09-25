"""Secure credential storage contracts for OAuth provider credentials.

The domain layer stores only opaque credential references and metadata. Raw
secrets are accepted transiently by the vault implementation and must never be
logged, serialized into domain models, or committed to source control.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class CredentialRef:
    """Opaque reference to secret material held by a credential vault."""

    credential_id: str
    platform: str
    account_id: str
    scopes: tuple[str, ...]
    expires_at: datetime | None = None
    refreshable: bool = False


class CredentialVault(Protocol):
    """Minimal contract a production encrypted/secret-manager backend must implement."""

    def put(
        self,
        *,
        platform: str,
        account_id: str,
        access_token: str,
        scopes: tuple[str, ...] = (),
        expires_at: datetime | None = None,
        refresh_token: str | None = None,
    ) -> CredentialRef: ...

    def get_secret(self, credential: CredentialRef) -> tuple[str, str | None]: ...

    def delete(self, credential: CredentialRef) -> None: ...


class InMemoryCredentialVault:
    """Non-production vault used only for tests/development.

    A real deployment must replace this with encrypted-at-rest storage or a
    managed secret service. Secrets are never exposed through ``CredentialRef``.
    """

    def __init__(self) -> None:
        self._secrets: dict[str, tuple[str, str | None]] = {}
        self._refs: dict[str, CredentialRef] = {}

    def put(
        self,
        *,
        platform: str,
        account_id: str,
        access_token: str,
        scopes: tuple[str, ...] = (),
        expires_at: datetime | None = None,
        refresh_token: str | None = None,
    ) -> CredentialRef:
        if not platform.strip() or not account_id.strip() or not access_token:
            raise ValueError("platform, account_id and access_token are required")
        if expires_at is not None and expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        credential_id = f"cred_{uuid4().hex}"
        ref = CredentialRef(
            credential_id=credential_id,
            platform=platform.strip().lower(),
            account_id=account_id.strip(),
            scopes=tuple(sorted(set(scopes))),
            expires_at=expires_at,
            refreshable=bool(refresh_token),
        )
        self._refs[credential_id] = ref
        self._secrets[credential_id] = (access_token, refresh_token)
        return ref

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


class EncryptedMemoryCredentialVault:
    """Process-memory vault with authenticated encryption for production composition tests.

    The master key must be supplied by an external secret manager/environment;
    it is never generated into source or persisted by this class.
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
        if expires_at is not None and expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        credential_id = f"cred_{uuid4().hex}"
        ref = CredentialRef(
            credential_id=credential_id, platform=platform.strip().lower(),
            account_id=account_id.strip(), scopes=tuple(sorted(set(scopes))),
            expires_at=expires_at, refreshable=bool(refresh_token))
        nonce = __import__("secrets").token_bytes(12)
        plaintext = (access_token + "\x00" + (refresh_token or "")).encode()
        ciphertext = self._aes.encrypt(nonce, plaintext, credential_id.encode())
        self._records[credential_id] = (ref, nonce, ciphertext)
        return ref

    def get_secret(self, credential: CredentialRef) -> tuple[str, str | None]:
        stored = self._records.get(credential.credential_id)
        if stored is None or stored[0] != credential:
            raise KeyError("unknown credential reference")
        if credential.expires_at is not None and credential.expires_at <= datetime.now(timezone.utc):
            raise PermissionError("credential is expired")
        plaintext = self._aes.decrypt(stored[1], stored[2], credential.credential_id.encode()).decode()
        access_token, _, refresh_token = plaintext.partition("\x00")
        return access_token, refresh_token or None

    def delete(self, credential: CredentialRef) -> None:
        self._records.pop(credential.credential_id, None)
