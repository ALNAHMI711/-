from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.replay_protection import InMemoryReplayGuard
from app.worker_http import MappingWorkerSecretResolver, create_worker_http_app
from app.worker_transport import create_envelope

SECRET = "test-worker-secret"
ISSUED = datetime.fromtimestamp(100, timezone.utc)
EXPIRES = datetime.fromtimestamp(110, timezone.utc)
NOW_BODY = "command"


def make_app(calls: list[str]):
    def handler(envelope):
        calls.append(envelope.message_id)

    return create_worker_http_app(
        MappingWorkerSecretResolver({"w1": SECRET}),
        handler,
        replay_guard=InMemoryReplayGuard(),
    )


def signed_payload(worker="w1", secret=SECRET, message_id="m1", body=NOW_BODY):
    envelope = create_envelope(secret, message_id, worker, ISSUED, EXPIRES, body)
    return {
        "message_id": envelope.message_id,
        "issued_at": envelope.issued_at.isoformat(),
        "expires_at": envelope.expires_at.isoformat(),
        "body": envelope.body,
        "authentication_tag": envelope.authentication_tag,
    }


def test_valid_message_is_accepted_and_handler_runs():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    response = client.post("/internal/workers/w1/messages", json=signed_payload())
    assert response.status_code == 202
    assert response.json() == {"accepted": True, "message_id": "m1"}
    assert calls == ["m1"]


def test_wrong_secret_is_unauthorized_and_handler_does_not_run():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    response = client.post(
        "/internal/workers/w1/messages",
        json=signed_payload(secret="wrong"),
    )
    assert response.status_code == 401
    assert calls == []


def test_wrong_worker_is_forbidden_and_handler_does_not_run():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    response = client.post(
        "/internal/workers/w2/messages",
        json=signed_payload(worker="w1"),
    )
    assert response.status_code == 403
    assert calls == []


def test_expired_message_is_bad_request_and_handler_does_not_run():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    payload = signed_payload()
    payload["expires_at"] = datetime.fromtimestamp(99, timezone.utc).isoformat()
    response = client.post("/internal/workers/w1/messages", json=payload)
    assert response.status_code == 400
    assert calls == []


def test_replay_is_conflict_and_handler_runs_only_once():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    payload = signed_payload()
    first = client.post("/internal/workers/w1/messages", json=payload)
    second = client.post("/internal/workers/w1/messages", json=payload)
    assert first.status_code == 202
    assert second.status_code == 409
    assert calls == ["m1"]


def test_malformed_payload_is_rejected_before_handler():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    response = client.post(
        "/internal/workers/w1/messages",
        json={"message_id": "m1", "body": "command"},
    )
    assert response.status_code == 422
    assert calls == []


def test_extra_secret_field_is_rejected():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    payload = signed_payload()
    payload["secret"] = SECRET
    response = client.post("/internal/workers/w1/messages", json=payload)
    assert response.status_code == 422
    assert calls == []
