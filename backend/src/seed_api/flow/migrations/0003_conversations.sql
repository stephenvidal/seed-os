-- Chat (M4): a conversation is an ordered series of tasks, one per message sent.
CREATE TABLE conversations (
    id         uuid PRIMARY KEY,
    owner      text        NOT NULL,
    title      text        NOT NULL,
    model      text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX conversations_recent ON conversations (owner, updated_at DESC);

-- A turn is a task. `context` is the conversation as it stood when the message was
-- sent (earlier prompts and answers), fixed at creation so a resumed or retried
-- turn sees exactly what the first attempt saw. `workspace_id` names the files the
-- task works on: a turn shares its conversation's workspace, a lone task has its own.
ALTER TABLE tasks
    ADD COLUMN conversation_id uuid REFERENCES conversations (id) ON DELETE CASCADE,
    ADD COLUMN turn            integer,
    ADD COLUMN context         jsonb NOT NULL DEFAULT '[]',
    ADD COLUMN workspace_id    uuid,
    ADD CONSTRAINT tasks_turn_unique UNIQUE (conversation_id, turn),
    ADD CONSTRAINT tasks_turn_pairs CHECK ((conversation_id IS NULL) = (turn IS NULL));

CREATE INDEX tasks_unfinished_turns ON tasks (conversation_id)
    WHERE conversation_id IS NOT NULL AND state IN ('queued', 'running');
