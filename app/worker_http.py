"""HTTP boundary for authenticated and structured worker commands."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Callable, Mapping, Protocol

from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from .replay_protection import InMemoryReplayGuard, ReplayGuard
from .worker_commands import CommandRejected, CommandType, WorkerCommand, WorkerCommandLedger
from .worker_transport import TransportEnvelope, TransportRejected, validate_envelope


class WorkerSecretResolver(Protocol):
    """Resolve a worker transport secret without exposing it to the HTTP client."""

    def resolve(self, worker_id: str) -> str | None:
        ...


@dataclass(frozen=True)
class MappingWorkerSecretResolver:
    """Simple resolver for tests/local development; production should use a secret store."""

    secrets: Mapping[str, str]

    def resolve(self, worker_id: str) -> str | None:
        return self.secrets.get(worker_id)


class WorkerMessage(BaseModel):
    """Wire representation of an authenticated worker envelope."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=200)
    issued_at: datetime
    expires_at: datetime
    body: str = Field(min_length=1, max_length=256_000)
    authentication_tag: str = Field(min_length=64, max_length=128)


class WorkerMessageResponse(BaseModel):
    accepted: bool = True
    message_id: str
    command_id: str | None = None
    command_status: str | None = None


_COMMAND_FIELDS = {
    "command_id",
    "command_type",
    "worker_id",
    "job_id",
    "job_type",
    "issued_at",
    "expires_at",
}


def parse_worker_command(body: str) -> WorkerCommand:
    """Parse a bounded JSON command; arbitrary shell/script payloads are forbidden."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CommandRejected("command body must be valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _COMMAND_FIELDS:
        raise CommandRejected("command payload has invalid fields")
    try:
        command_type = CommandType(payload["command_type"])
        issued_at = datetime.fromisoformat(payload["issued_at"])
        expires_at = datetime.fromisoformat(payload["expires_at"])
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("command timestamps must be timezone-aware")
        return WorkerCommand(
            command_id=str(payload["command_id"]),
            command_type=command_type,
            worker_id=str(payload["worker_id"]),
            job_id=payload["job_id"],
            job_type=payload["job_type"],
            issued_at=issued_at,
            expires_at=expires_at,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CommandRejected("invalid worker command") from exc


def _classify_rejection(error: TransportRejected) -> tuple[int, str]:
    message = str(error)
    if message in {"authentication failed", "authentication secret is missing"}:
        return 401, "worker authentication failed"
    if message == "worker identity mismatch":
        return 403, "worker identity rejected"
    if message == "message replay detected":
        return 409, "message replay detected"
    return 400, "invalid worker message"


def create_worker_http_app(
    secret_resolver: WorkerSecretResolver,
    handler: Callable[[WorkerCommand], None],
    replay_guard: ReplayGuard | None = None,
    command_ledger: WorkerCommandLedger | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Create the internal worker HTTP app.

    Transport authentication runs before command parsing. The handler receives
    only a validated WorkerCommand and never receives raw shell/script input.
    """
    if replay_guard is None:
        replay_guard = InMemoryReplayGuard()
    if command_ledger is None:
        command_ledger = WorkerCommandLedger()
    now_fn = clock or (lambda: datetime.now(timezone.utc))

    app = FastAPI(title="Mashahid Worker Transport", docs_url=None, redoc_url=None)

    @app.post(
        "/internal/workers/{worker_id}/messages",
        response_model=WorkerMessageResponse,
        status_code=202,
    )
    def receive_message(
        payload: WorkerMessage,
        worker_id: str = Path(min_length=1, max_length=200),
    ) -> WorkerMessageResponse:
        if payload.issued_at.tzinfo is None or payload.expires_at.tzinfo is None:
            raise HTTPException(status_code=400, detail="timestamps must include timezone")
        current = now_fn()
        if current.tzinfo is None:
            raise HTTPException(status_code=500, detail="server clock must be timezone-aware")
        try:
            envelope = TransportEnvelope(
                message_id=payload.message_id,
                worker_id=worker_id,
                issued_at=payload.issued_at,
                expires_at=payload.expires_at,
                body=payload.body,
                authentication_tag=payload.authentication_tag,
            )
            secret = secret_resolver.resolve(worker_id)
            validate_envelope(
                envelope,
                expected_worker_id=worker_id,
                secret=secret or "",
                now=current,
                replay_guard=replay_guard,
            )
        except ValueError as error:
            if isinstance(error, TransportRejected):
                status, detail = _classify_rejection(error)
                raise HTTPException(status_code=status, detail=detail) from error
            raise HTTPException(status_code=400, detail="malformed worker message") from error

        try:
            command = parse_worker_command(envelope.body)
            result = command_ledger.accept(command, worker_id, now=current)
        except CommandRejected as error:
            raise HTTPException(status_code=400, detail="invalid or unauthorized worker command") from error

        handler(command)
        return WorkerMessageResponse(
            message_id=envelope.message_id,
            command_id=result.command_id,
            command_status=result.status.value,
        )

    return app
