"""Authenticated outbound worker transport contracts."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest, new

from .replay_protection import ReplayGuard


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("transport timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def canonical_payload(message_id: str, worker_id: str, issued_at: datetime, expires_at: datetime, body: str) -> bytes:
    """Return deterministic bytes authenticated by HMAC-SHA256."""
    if not message_id.strip() or not worker_id.strip():
        raise ValueError("message_id and worker_id are required")
    if not body:
        raise ValueError("body is required")
    fields = ("mashahid-worker-v1", message_id, worker_id, _utc_timestamp(issued_at), _utc_timestamp(expires_at), body)
    return "\n".join(fields).encode("utf-8")


def sign_envelope(secret: str, message_id: str, worker_id: str, issued_at: datetime, expires_at: datetime, body: str) -> str:
    if not secret:
        raise ValueError("transport secret is required")
    return new(secret.encode("utf-8"), canonical_payload(message_id, worker_id, issued_at, expires_at, body), sha256).hexdigest()


@dataclass(frozen=True)
class TransportEnvelope:
    message_id: str
    worker_id: str
    issued_at: datetime
    expires_at: datetime
    body: str
    authentication_tag: str

    def __post_init__(self) -> None:
        canonical_payload(self.message_id, self.worker_id, self.issued_at, self.expires_at, self.body)
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if not self.authentication_tag:
            raise ValueError("authentication_tag is required")

    def expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return current >= self.expires_at


def create_envelope(secret: str, message_id: str, worker_id: str, issued_at: datetime, expires_at: datetime, body: str) -> TransportEnvelope:
    return TransportEnvelope(message_id, worker_id, issued_at, expires_at, body, sign_envelope(secret, message_id, worker_id, issued_at, expires_at, body))


class TransportRejected(ValueError):
    """Raised when a worker message fails transport-level validation."""


def validate_envelope(
    envelope: TransportEnvelope,
    expected_worker_id: str,
    secret: str,
    now: datetime | None = None,
    replay_guard: ReplayGuard | None = None,
) -> None:
    """Validate identity, freshness and HMAC, then atomically consume the message ID."""
    if not expected_worker_id.strip() or envelope.worker_id != expected_worker_id:
        raise TransportRejected("worker identity mismatch")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if envelope.expired(current):
        raise TransportRejected("message has expired")
    if not secret:
        raise TransportRejected("authentication secret is missing")
    expected_tag = sign_envelope(secret, envelope.message_id, envelope.worker_id, envelope.issued_at, envelope.expires_at, envelope.body)
    if not compare_digest(envelope.authentication_tag, expected_tag):
        raise TransportRejected("authentication failed")
    if replay_guard is not None:
        ttl_seconds = max(1, int((envelope.expires_at - current).total_seconds()))
        if not replay_guard.claim(envelope.message_id, envelope.worker_id, ttl_seconds):
            raise TransportRejected("message replay detected")
