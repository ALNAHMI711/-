-- Durable job metadata for resumable provider operations.
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_jobs_type_state
    ON jobs (job_type, state);
