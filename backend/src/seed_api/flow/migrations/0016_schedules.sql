-- Schedules (M8, D-029): a saved task that starts on a timetable. A worker starts it
-- when `next_run_at` has passed (exactly once per due time), then sets the next one.
CREATE TABLE schedules (
    id            uuid PRIMARY KEY,
    owner         text        NOT NULL,
    name          text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    prompt        text        NOT NULL CHECK (char_length(prompt) BETWEEN 1 AND 20000),
    model         text        NOT NULL,
    -- Runs in this project, like a task started there (D-023); gone with the project.
    project_id    uuid REFERENCES projects (id) ON DELETE CASCADE,
    kind          text        NOT NULL CHECK (kind IN ('interval', 'daily')),
    every_minutes integer     CHECK (every_minutes BETWEEN 5 AND 10080),
    at_time       time,
    timezone      text        NOT NULL DEFAULT 'UTC',
    enabled       boolean     NOT NULL DEFAULT true,
    -- NULL while disabled.
    next_run_at   timestamptz,
    last_run_at   timestamptz,
    -- 'started', or 'skipped_busy' when the previous run was still going.
    last_outcome  text CHECK (last_outcome IN ('started', 'skipped_busy')),
    last_task_id  uuid REFERENCES tasks (id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'interval' AND every_minutes IS NOT NULL AND at_time IS NULL)
        OR (kind = 'daily' AND at_time IS NOT NULL AND every_minutes IS NULL)),
    CHECK (enabled = (next_run_at IS NOT NULL))
);

CREATE INDEX schedules_due ON schedules (next_run_at) WHERE enabled;
CREATE INDEX schedules_owner ON schedules (owner, lower(name));
