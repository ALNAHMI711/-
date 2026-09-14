from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient

from app.replay_protection import InMemoryReplayGuard
from app.worker_http import MappingWorkerSecretResolver, create_worker_http_app
from app.worker_transport import create_envelope

SECRET = "test-worker-secret"
ISSUED = datetime.fromtimestamp(1_000, timezone.utc)
EXPIRES = datetime.fromtimestamp(1_030, timezone.utc)
NOW = datetime.fromtimestamp(1_001, timezone.utc)


def command_body(worker="w1", command_id="cmd-1", job_id="job-1", issued_at=ISSUED, expires_at=EXPIRES):
    return json.dumps({
        "command_id": command_id,
        "command_type": "execute_job",
        "worker_id": worker,
        "job_id": job_id,
        "job_type": "content_publish",
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    })


def make_app(calls: list[str]):
    def handler(command):
        calls.append(command.command_id)

    return create_worker_http_app(
        MappingWorkerSecretResolver({"w1": SECRET}),
        handler,
        replay_guard=InMemoryReplayGuard(),
        clock=lambda: NOW,
    )


def signed_payload(worker="w1", secret=SECRET, message_id="m1", body=None, issued_at=ISSUED, expires_at=EXPIRES):
    body = body or command_body(worker=worker, issued_at=issued_at, expires_at=expires_at)
    envelope = create_envelope(secret, message_id, worker, issued_at, expires_at, body)
    return {
        "message_id": envelope.message_id,
        "issued_at": envelope.issued_at.isoformat(),
        "expires_at": envelope.expires_at.isoformat(),
        "body": envelope.body,
        "authentication_tag": envelope.authentication_tag,
    }


def test_valid_message_is_accepted_and_structured_command_reaches_handler():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    response = client.post("/internal/workers/w1/messages", json=signed_payload())
    assert response.status_code == 202
    assert response.json() == {"accepted": True, "message_id": "m1", "command_id": "cmd-1", "command_status": "accepted"}
    assert calls == ["cmd-1"]


def test_wrong_secret_is_unauthorized_and_handler_does_not_run():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    response = client.post("/internal/workers/w1/messages", json=signed_payload(secret="wrong"))
    assert response.status_code == 401
    assert calls == []


def test_wrong_worker_path_is_authentication_failure_and_handler_does_not_run():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    response = client.post("/internal/workers/w2/messages", json=signed_payload(worker="w1"))
    assert response.status_code == 401
    assert calls == []


def test_expired_message_is_bad_request_and_handler_does_not_run():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    issued = NOW - timedelta(seconds=30)
    expired = NOW - timedelta(seconds=1)
    payload = signed_payload(
        body=command_body(issued_at=issued, expires_at=expired),
        issued_at=issued,
        expires_at=expired,
    )
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
    assert calls == ["cmd-1"]


def test_malformed_command_body_is_rejected_before_handler():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    response = client.post("/internal/workers/w1/messages", json=signed_payload(body="not-json"))
    assert response.status_code == 400
    assert calls == []


def test_unknown_command_field_is_rejected():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    payload = json.loads(command_body())
    payload["shell"] = "rm -rf /"
    response = client.post("/internal/workers/w1/messages", json=signed_payload(body=json.dumps(payload)))
    assert response.status_code == 400
    assert calls == []


def test_extra_secret_field_is_rejected():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    payload = signed_payload()
    payload["secret"] = SECRET
    response = client.post("/internal/workers/w1/messages", json=payload)
    assert response.status_code == 422
    assert calls == []


def test_missing_required_envelope_field_is_rejected():
    calls: list[str] = []
    client = TestClient(make_app(calls))
    payload = signed_payload()
    del payload["authentication_tag"]
    response = client.post("/internal/workers/w1/messages", json=payload)
    assert response.status_code == 422
    assert calls == []
