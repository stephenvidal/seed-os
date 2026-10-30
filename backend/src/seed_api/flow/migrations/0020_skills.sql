-- Skills (M8, D-033): procedures the owner saves, in the shape of a Hermes Agent
-- SKILL.md. A task's prompt lists each skill by name and description; the agent
-- reads one in full when a request matches it. A skill with an agent is private
-- to that agent; one without is shared with SEED and the agents allowed it.
CREATE TABLE skills (
    id          uuid PRIMARY KEY,
    owner       text        NOT NULL,
    agent_id    uuid REFERENCES agents (id) ON DELETE CASCADE,
    -- Lower case, so `/name` in a message names it exactly.
    name        text        NOT NULL CHECK (name ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
    description text        NOT NULL CHECK (char_length(description) BETWEEN 1 AND 1024),
    tags        text[]      NOT NULL DEFAULT '{}',
    body        text        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 20000),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- One name per owner across shared and private skills, so a name is never ambiguous.
CREATE UNIQUE INDEX skills_name ON skills (owner, name);
