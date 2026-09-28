-- Durable job metadata for resumable provider operations.
-- Upload-session URLs are stored only in encrypted metadata by the application.

ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_jobs_type_state
    ON jobs (job_type, state);
