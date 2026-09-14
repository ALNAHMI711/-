from datetime import datetime, timezone

import pytest

from app.worker_transport import TransportEnvelope, TransportRejected, create_envelope, sign_envelope, validate_envelope


SECRET = "test-worker-secret"
ISSUED = datetime.fromtimestamp(100, timezone.utc)
EXPIRES = datetime.fromtimestamp(110, timezone.utc)
NOW = datetime.fromtimestamp(101, timezone.utc)


def envelope(worker="w1", body="command", secret=SECRET, message_id="m1"):
    return create_envelope(secret, message_id, worker, ISSUED, EXPIRES, body)


def test_valid_hmac_envelope_is_accepted():
    validate_envelope(envelope(), "w1", SECRET, NOW)


def test_wrong_secret_and_worker_are_rejected():
    with pytest.raises(TransportRejected):
        validate_envelope(envelope(), "w1", "wrong", NOW)
    with pytest.raises(TransportRejected):
        validate_envelope(envelope(), "w2", SECRET, NOW)


def test_body_tampering_is_rejected():
    original = envelope()
    tampered = TransportEnvelope(original.message_id, original.worker_id, original.issued_at, original.expires_at, "tampered", original.authentication_tag)
    with pytest.raises(TransportRejected):
        validate_envelope(tampered, "w1", SECRET, NOW)


def test_timestamp_tampering_is_rejected():
    original = envelope()
    tampered = TransportEnvelope(original.message_id, original.worker_id, datetime.fromtimestamp(102, timezone.utc), original.expires_at, original.body, original.authentication_tag)
    with pytest.raises(TransportRejected):
        validate_envelope(tampered, "w1", SECRET, NOW)


def test_expired_envelope_is_rejected():
    expired = create_envelope(SECRET, "m1", "w1", ISSUED, datetime.fromtimestamp(101, timezone.utc), "command")
    with pytest.raises(TransportRejected):
        validate_envelope(expired, "w1", SECRET, datetime.fromtimestamp(101, timezone.utc))


def test_signature_is_deterministic():
    first = sign_envelope(SECRET, "m1", "w1", ISSUED, EXPIRES, "command")
    second = sign_envelope(SECRET, "m1", "w1", ISSUED, EXPIRES, "command")
    assert first == second
    assert len(first) == 64
