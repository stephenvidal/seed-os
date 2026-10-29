-- Projects (M6, D-017): a named group of conversations with instructions the model
-- sees on every turn of them. Deleting a project keeps its conversations; they
-- leave the project.
CREATE TABLE projects (
    id           uuid PRIMARY KEY,
    owner        text        NOT NULL,
    name         text        NOT NULL,
    instructions text        NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX projects_recent ON projects (owner, updated_at DESC);

ALTER TABLE conversations
    ADD COLUMN project_id uuid REFERENCES projects (id) ON DELETE SET NULL;

CREATE INDEX conversations_project ON conversations (project_id) WHERE project_id IS NOT NULL;

-- The project instructions as they stood when the turn was sent, fixed like
-- `context` so a retried or resumed turn sees what the first attempt saw.
ALTER TABLE tasks ADD COLUMN instructions text;
