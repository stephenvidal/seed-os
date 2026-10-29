-- Studio previews (M6, ADR-0015): a short-lived link that serves one workspace's
-- saved files to a sandboxed frame. The sandboxed page has no cookies, so the link
-- itself is the permission; only its SHA-256 is stored.
CREATE TABLE artifact_previews (
    token_hash   text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    workspace_id uuid        NOT NULL,
    created_by   text        NOT NULL,
    expires_at   timestamptz NOT NULL
);

CREATE INDEX artifact_previews_expiry ON artifact_previews (expires_at);
