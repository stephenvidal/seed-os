-- SEED Flow: durable tasks and their append-only event log.
CREATE TABLE tasks (
    id               uuid PRIMARY KEY,
    created_by       text        NOT NULL,
    title            text        NOT NULL,
    model            text        NOT NULL,
    prompt           text        NOT NULL,
    state            text        NOT NULL
        CHECK (state IN ('queued', 'running', 'completed', 'failed', 'canceled')),
    idempotency_key  text,
    attempt          integer     NOT NULL DEFAULT 0,
    max_attempts     integer     NOT NULL CHECK (max_attempts >= 1),
    cancel_requested boolean     NOT NULL DEFAULT false,
    lease_owner      text,
    lease_expires_at timestamptz,
    checkpoint       jsonb,
    termination      text,
    error            text,
    result_text      text,
    usage            jsonb       NOT NULL DEFAULT '{"input_tokens": 0, "output_tokens": 0}',
    last_seq         bigint      NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    started_at       timestamptz,
    finished_at      timestamptz,
    UNIQUE (created_by, idempotency_key)
);

CREATE INDEX tasks_claimable ON tasks (created_at) WHERE state IN ('queued', 'running');
CREATE INDEX tasks_newest ON tasks (created_at DESC);

CREATE TABLE task_events (
    task_id    uuid        NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    seq        bigint      NOT NULL,
    attempt    integer     NOT NULL,
    type       text        NOT NULL,
    data       jsonb       NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, seq)
);
