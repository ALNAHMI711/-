# Job Queue

The queue is the control-plane contract between scheduling and compute workers.

## Lifecycle

`QUEUED -> RUNNING -> SUCCEEDED`

A running job may become `QUEUED` again after a retryable failure or expired worker lease, up to `max_attempts`. Otherwise it becomes `FAILED`. Queued or running jobs may be `CANCELLED`.

## Reliability

- Every job has an idempotency key to prevent duplicate enqueue operations.
- Claims use a time-bounded lease so a dead worker cannot hold a job forever.
- Expired leases are reclaimed and can be routed to another healthy worker.
- Production persistence should use a transactional database and a distributed lease/lock mechanism; this module is the framework-neutral reference implementation.
- Errors are bounded and must not contain secrets or tokens.
