-- Project knowledge (M6, D-021): text documents the owner adds to a project,
-- split into chunks the agent searches with Postgres full-text search.
CREATE TABLE knowledge_documents (
    id         uuid PRIMARY KEY,
    project_id uuid        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    name       text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
    chars      integer     NOT NULL,
    chunks     integer     NOT NULL,
    created_by text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT knowledge_documents_name UNIQUE (project_id, name)
);

CREATE TABLE knowledge_chunks (
    document_id uuid    NOT NULL REFERENCES knowledge_documents (id) ON DELETE CASCADE,
    project_id  uuid    NOT NULL,
    seq         integer NOT NULL,
    content     text    NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    PRIMARY KEY (document_id, seq)
);

CREATE INDEX knowledge_chunks_search ON knowledge_chunks USING gin (tsv);
CREATE INDEX knowledge_chunks_project ON knowledge_chunks (project_id);
