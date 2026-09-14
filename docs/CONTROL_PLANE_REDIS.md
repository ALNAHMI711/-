# Control-plane Redis boundary

The control plane may use Redis for distributed leases and worker coordination.
A Redis outage must not erase durable jobs: PostgreSQL is authoritative.

Workers must prove ownership before lease renewal/release, and lease keys must
expire automatically. This boundary is intentionally separate from OAuth and
credential storage.
