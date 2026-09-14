"""Application-level routing for authenticated worker commands.

The HTTP transport only authenticates and validates commands. This module owns
application authorization and lifecycle transitions; it never executes shell
text from a worker message.
"""

from dataclasses import dataclass
from typing import Callable

from .compute_nodes import ComputeNodeManager
from .control_plane import ControlPlane, DispatchError
from .worker_commands import CommandType, WorkerCommand


class WorkerCommandHandlerError(RuntimeError):
    """Raised when a worker command is not authorized or cannot be applied."""


ExecuteCallback = Callable[[WorkerCommand], bool]


@dataclass
class WorkerCommandHandler:
    """Route validated worker commands into safe domain operations."""

    control_plane: ControlPlane
    nodes: ComputeNodeManager
    execute_callback: ExecuteCallback | None = None

    def __call__(self, command: WorkerCommand) -> None:
        if command.command_type is CommandType.EXECUTE_JOB:
            self._execute(command)
        elif command.command_type is CommandType.CANCEL_JOB:
            self._cancel(command)
        elif command.command_type is CommandType.DRAIN:
            self._drain(command)
        else:  # pragma: no cover - Enum validation makes this defensive only.
            raise WorkerCommandHandlerError("unsupported worker command")

    def _execute(self, command: WorkerCommand) -> None:
        if not command.job_id:
            raise WorkerCommandHandlerError("execute_job requires job_id")
        try:
            job = self.control_plane.queue.get(command.job_id)
        except KeyError as exc:
            raise WorkerCommandHandlerError("job not found") from exc
        if job.worker_id != command.worker_id:
            raise WorkerCommandHandlerError("worker does not own job")
        if job.job_type != command.job_type:
            raise WorkerCommandHandlerError("job type mismatch")
        if self.execute_callback is None:
            raise WorkerCommandHandlerError("no execution callback configured")
        try:
            accepted = bool(self.execute_callback(command))
        except Exception as exc:
            raise WorkerCommandHandlerError("worker execution callback failed") from exc
        if not accepted:
            raise WorkerCommandHandlerError("worker rejected job execution")

    def _cancel(self, command: WorkerCommand) -> None:
        if not command.job_id:
            raise WorkerCommandHandlerError("cancel_job requires job_id")
        try:
            self.control_plane.cancel(command.job_id, worker_id=command.worker_id)
        except (DispatchError, KeyError, ValueError) as exc:
            raise WorkerCommandHandlerError("worker cannot cancel this job") from exc

    def _drain(self, command: WorkerCommand) -> None:
        try:
            self.nodes.mark_draining(command.worker_id)
        except KeyError as exc:
            raise WorkerCommandHandlerError("unknown worker") from exc
