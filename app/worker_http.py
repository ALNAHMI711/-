"""HTTP boundary for authenticated worker messages."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol

from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from .replay_protection import InMemoryReplayGuard, ReplayGuard
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


def _classify_rejection(error: TransportRejected) -> tuple[int, str]:
    message = str(error)
    if message == "authentication failed" or message == "authentication secret is missing":
        return 401, "worker authentication failed"
    if message == "worker identity mismatch":
        return 403, "worker identity rejected"
    if message == "message replay detected":
        return 409, "message replay detected"
    return 400, "invalid worker message"


def create_worker_http_app(
    secret_resolver: WorkerSecretResolver,
    handler: Callable[[TransportEnvelope], None],
    replay_guard: ReplayGuard | None = None,
) -> FastAPI:
    """Create the internal worker HTTP app.

    Validation happens before the handler is called. The request never carries
    a worker secret; the server resolves it internally and consumes the message
    ID atomically through the supplied replay guard.
    """
    if replay_guard is None:
        replay_guard = InMemoryReplayGuard()

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
                replay_guard=replay_guard,
            )
        except ValueError as error:
            if isinstance(error, TransportRejected):
                status, detail = _classify_rejection(error)
                raise HTTPException(status_code=status, detail=detail) from error
            raise HTTPException(status_code=400, detail="malformed worker message") from error

        handler(envelope)
        return WorkerMessageResponse(message_id=envelope.message_id)

    return app
