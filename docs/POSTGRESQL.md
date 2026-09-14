# PostgreSQL persistence

The control plane now has a real PostgreSQL adapter for durable job state.

## Production rules

- `migrations/001_initial.sql` creates the durable jobs table and uniqueness constraints.
- `app/postgres.py` uses parameterized SQL and transactions through `psycopg`.
- `job_id` and `idempotency_key` are database-enforced unique identifiers.
- Lease and worker fields are persisted with the job state.
- Secrets, OAuth tokens, passwords, and API keys are intentionally excluded.
- Redis will be used later for distributed coordination/leases, not as the durable source of truth.

Integration tests that require a live PostgreSQL instance should run against an isolated database in CI before this adapter is used for production traffic.
