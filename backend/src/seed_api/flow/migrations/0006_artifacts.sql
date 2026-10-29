-- Artifacts (M6, ADR-0014): every file a task leaves in its workspace, saved after
-- each run with a version per change. Content lives on disk under its SHA-256;
-- these rows say which file had which content when. A conversation's turns share
-- one workspace, so its files are one set of artifacts; a lone task has its own.
CREATE TABLE artifacts (
    id              uuid PRIMARY KEY,
    workspace_id    uuid        NOT NULL,
    conversation_id uuid REFERENCES conversations (id) ON DELETE CASCADE,
    path            text        NOT NULL CHECK (length(path) BETWEEN 1 AND 512),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, path)
);

CREATE INDEX artifacts_recent ON artifacts (updated_at DESC);

-- A version with no content (sha256 and size NULL) records that the file was
-- deleted; a later version brings it back.
CREATE TABLE artifact_versions (
    artifact_id uuid        NOT NULL REFERENCES artifacts (id) ON DELETE CASCADE,
    version     integer     NOT NULL CHECK (version >= 1),
    task_id     uuid REFERENCES tasks (id) ON DELETE SET NULL,
    sha256      text CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size        bigint CHECK (size >= 0),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_id, version),
    CHECK ((sha256 IS NULL) = (size IS NULL))
);
