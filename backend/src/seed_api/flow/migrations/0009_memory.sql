-- Project memory (M6, D-018): short notes the model sees in every chat of a
-- project. The agent can only propose one; it reaches the model after the owner
-- approves it. Owners add approved notes directly. Rejecting deletes.
CREATE TABLE project_memories (
    id                     uuid PRIMARY KEY,
    project_id             uuid        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    content                text        NOT NULL CHECK (char_length(content) BETWEEN 1 AND 500),
    status                 text        NOT NULL CHECK (status IN ('proposed', 'approved')),
    -- Who wrote it: 'agent', or the owner's username.
    created_by             text        NOT NULL,
    source_task_id         uuid        REFERENCES tasks (id) ON DELETE SET NULL,
    source_conversation_id uuid        REFERENCES conversations (id) ON DELETE SET NULL,
    approved_by            text,
    approved_at            timestamptz,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    -- A retried run proposes the same note once.
    CONSTRAINT project_memories_once UNIQUE (source_task_id, content)
);

CREATE INDEX project_memories_by_project ON project_memories (project_id, status, updated_at DESC);

-- Fixed when a turn is sent, like `instructions`: the project it ran in (for the
-- memory tool) and the approved notes it was given.
ALTER TABLE tasks
    ADD COLUMN project_id uuid,
    ADD COLUMN memory     text;
