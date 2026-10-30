-- Notifications (M8, D-030): what a person should hear about without watching, kept
-- until they are read. Written in the same transaction as the change they report.
CREATE TABLE notifications (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner       text        NOT NULL,
    kind        text        NOT NULL CHECK (
        kind IN ('task_completed', 'task_failed', 'approval_needed', 'schedule_skipped')
    ),
    title       text        NOT NULL,
    body        text        NOT NULL DEFAULT '',
    -- Gone with the task or schedule they are about.
    task_id     uuid REFERENCES tasks (id) ON DELETE CASCADE,
    schedule_id uuid REFERENCES schedules (id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    read_at     timestamptz
);
CREATE INDEX notifications_owner ON notifications (owner, created_at DESC);
CREATE INDEX notifications_unread ON notifications (owner) WHERE read_at IS NULL;
