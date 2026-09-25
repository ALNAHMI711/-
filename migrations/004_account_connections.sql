-- Durable project/account linkage metadata.
-- OAuth tokens, client secrets, and platform passwords are never stored here.

CREATE TABLE IF NOT EXISTS account_connections (
    account_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    connection_state TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    monetization_state TEXT NOT NULL,
    permissions TEXT[] NOT NULL DEFAULT '{}',
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_connections_project
    ON account_connections (project_id, platform, account_id);

CREATE INDEX IF NOT EXISTS idx_account_connections_state
    ON account_connections (connection_state, verification_state);
