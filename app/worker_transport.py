"""Authenticated outbound worker transport contracts."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hmac import compare_digest


@dataclass(frozen=True)
class TransportEnvelope:
    message_id: str
    worker_id: str
    issued_at: datetime
    expires_at: datetime
    body: str
    authentication_tag: str

    def __post_init__(self) -> None:
        if not self.message_id.strip() or not self.worker_id.strip():
            raise ValueError("message_id and worker_id are required")
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("transport timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if not self.body or not self.authentication_tag:
            raise ValueError("body and authentication_tag are required")

    def expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return current >= self.expires_at


class TransportRejected(ValueError):
    """Raised when a worker message fails transport-level validation."""


def validate_envelope(envelope: TransportEnvelope, expected_worker_id: str, expected_authentication_tag: str, now: datetime | None = None) -> None:
    if not expected_worker_id.strip() or envelope.worker_id != expected_worker_id:
        raise TransportRejected("worker identity mismatch")
    if envelope.expired(now):
        raise TransportRejected("message has expired")
    if not compare_digest(envelope.authentication_tag, expected_authentication_tag):
        raise TransportRejected("authentication failed")
