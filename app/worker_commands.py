"""Safe worker-command contracts for the Mashahid control plane.

Commands contain job metadata only. Secrets, access tokens and passwords must
never be embedded in command payloads.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class CommandType(str, Enum):
    EXECUTE_JOB = "execute_job"
    CANCEL_JOB = "cancel_job"
    DRAIN = "drain"


class CommandStatus(str, Enum):
    ACCEPTED = "accepted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class WorkerCommand:
    command_id: str
    command_type: CommandType
    worker_id: str
    job_id: str | None
    job_type: str | None
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.command_id.strip() or not self.worker_id.strip():
            raise ValueError("command_id and worker_id are required")
        if self.command_type is CommandType.EXECUTE_JOB and (not self.job_id or not self.job_type):
            raise ValueError("execute_job requires job_id and job_type")
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("command timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")

    def is_expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return current >= self.expires_at


@dataclass(frozen=True)
class CommandResult:
    command_id: str
    worker_id: str
    status: CommandStatus
    error: str | None = None


class CommandRejected(ValueError):
    """Raised when a command cannot safely be accepted."""


class WorkerCommandLedger:
    """In-memory idempotency ledger; production should use durable storage."""

    def __init__(self) -> None:
        self._results: dict[str, CommandResult] = {}

    def get(self, command_id: str) -> CommandResult | None:
        """Return a prior result without mutating the ledger."""
        return self._results.get(command_id)

    def accept(self, command: WorkerCommand, worker_id: str, now: datetime | None = None) -> CommandResult:
        if command.worker_id != worker_id:
            raise CommandRejected("command targets a different worker")
        if command.is_expired(now):
            raise CommandRejected("command has expired")
        existing = self._results.get(command.command_id)
        if existing is not None:
            if existing.worker_id != worker_id:
                raise CommandRejected("worker does not own command")
            return existing
        result = CommandResult(command.command_id, worker_id, CommandStatus.ACCEPTED)
        self._results[command.command_id] = result
        return result

    def finish(self, command_id: str, worker_id: str, success: bool, error: str = "") -> CommandResult:
        existing = self._results.get(command_id)
        if existing is None:
            raise CommandRejected("command was not accepted")
        if existing.worker_id != worker_id:
            raise CommandRejected("worker does not own command")
        if existing.status not in {CommandStatus.ACCEPTED}:
            return existing
        status = CommandStatus.SUCCEEDED if success else CommandStatus.FAILED
        result = CommandResult(command_id, worker_id, status, None if success else error.strip()[:500] or "command failed")
        self._results[command_id] = result
        return result
