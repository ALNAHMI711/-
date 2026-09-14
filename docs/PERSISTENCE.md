# Persistence boundary

The control plane now has a repository boundary for durable state. `app/persistence.py` defines the job persistence contract and a deterministic in-memory implementation for tests.

## Production target

- PostgreSQL is the authoritative durable store.
- Repository methods must use transactions and database uniqueness for `job_id` and `idempotency_key`.
- Queue/lease state must remain consistent with worker ownership.
- Secrets and access tokens must not be persisted in job rows.
- Redis will be introduced later for distributed leases/coordination; it is not the source of truth for durable job history.

The in-memory repository is explicitly **not** a production database.
