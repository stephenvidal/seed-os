-- Agent definitions (M7, D-024): specialists the assistant can hand a sub-task
-- to. Each runs as its own task with these instructions, this model (or the
-- delegating task's when NULL) and only these tools.
CREATE TABLE agents (
    id           uuid PRIMARY KEY,
    owner        text        NOT NULL,
    name         text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 40),
    -- What the agent is for; the assistant reads it to choose whom to delegate to.
    description  text        NOT NULL CHECK (char_length(description) BETWEEN 1 AND 500),
    instructions text        NOT NULL DEFAULT '',
    model        text,
    tools        text[]      NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX agents_name ON agents (owner, lower(name));

-- Owners who were given the starter agents, so deleting them does not bring them
-- back.
CREATE TABLE agent_starters (
    owner      text PRIMARY KEY,
    given_at   timestamptz NOT NULL DEFAULT now()
);
