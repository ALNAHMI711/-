-- Index for durable provider operations and resumable uploads.
-- The metadata JSONB column is already created in 001_initial.sql.
CREATE INDEX IF NOT EXISTS idx_jobs_type_state
    ON jobs (job_type, state);
