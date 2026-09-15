-- Durable project/channel configuration. Provider credentials and OAuth tokens
-- are intentionally excluded and belong in the credential vault.

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'ar',
    topics TEXT[] NOT NULL DEFAULT '{}',
    content_rules TEXT[] NOT NULL DEFAULT '{}',
    automation_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_owner
    ON projects (owner_id, project_id);
