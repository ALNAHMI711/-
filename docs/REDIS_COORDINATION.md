# Redis coordination

Redis is a coordination layer, not the durable database.

## Responsibilities

- short-lived worker/job leases;
- distributed coordination between workers;
- lease renewal and expiry;
- preventing two workers from executing the same leased job concurrently.

## Source of truth

PostgreSQL remains authoritative for durable job history, state, attempts and
idempotency. Redis loss must not erase job history.

The current `InMemoryLeaseCoordinator` is a deterministic test implementation.
The production adapter must use Redis atomic operations (for example `SET NX`
with an expiry and owner-checked Lua/transactional release and renewal).

No passwords, OAuth tokens or platform secrets belong in lease values.
