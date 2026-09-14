from datetime import datetime, timezone

import pytest

from app.worker_transport import TransportEnvelope, TransportRejected, validate_envelope


def envelope(worker="w1", expires=110.0, tag="secret"):
    return TransportEnvelope("m1", worker, datetime.fromtimestamp(100, timezone.utc), datetime.fromtimestamp(expires, timezone.utc), "command", tag)


def test_valid_envelope_is_accepted():
    validate_envelope(envelope(), "w1", "secret", datetime.fromtimestamp(101, timezone.utc))


def test_identity_and_authentication_are_rejected():
    with pytest.raises(TransportRejected):
        validate_envelope(envelope(), "w2", "secret", datetime.fromtimestamp(101, timezone.utc))
    with pytest.raises(TransportRejected):
        validate_envelope(envelope(), "w1", "wrong", datetime.fromtimestamp(101, timezone.utc))


def test_expired_envelope_is_rejected():
    with pytest.raises(TransportRejected):
        validate_envelope(envelope(expires=101), "w1", "secret", datetime.fromtimestamp(101, timezone.utc))
