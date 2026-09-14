-- Durable control-plane job state. Secrets and access tokens do not belong here.

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL CHECK (max_attempts > 0),
    worker_id TEXT,
    lease_until TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_state_lease
    ON jobs (state, lease_until);

CREATE INDEX IF NOT EXISTS idx_jobs_worker_state
    ON jobs (worker_id, state);
