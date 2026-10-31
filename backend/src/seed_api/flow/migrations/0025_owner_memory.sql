-- Memory about the owner (M9, D-040): short notes SEED is given in every one of its
-- own runs, whatever the chat or project. SEED only proposes a note; it is used
-- after the owner approves it (Stephen's choice, 2026-10-31). Rejecting deletes.
CREATE TABLE owner_memories (
    id                     uuid PRIMARY KEY,
    owner                  text        NOT NULL,
    content                text        NOT NULL CHECK (char_length(content) BETWEEN 1 AND 500),
    status                 text        NOT NULL CHECK (status IN ('proposed', 'approved')),
    -- Who wrote it: 'agent', or the owner's username.
    created_by             text        NOT NULL,
    source_task_id         uuid        REFERENCES tasks (id) ON DELETE SET NULL,
    source_conversation_id uuid        REFERENCES conversations (id) ON DELETE SET NULL,
    approved_at            timestamptz,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    -- A retried run proposes the same note once.
    CONSTRAINT owner_memories_once UNIQUE (source_task_id, content)
);

CREATE INDEX owner_memories_by_owner ON owner_memories (owner, status, updated_at DESC);
