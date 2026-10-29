-- Accounts, revocable server-side sessions, and the audit log (ADR-0009).
CREATE TABLE users (
    id            uuid        PRIMARY KEY,
    username      text        NOT NULL UNIQUE
        CHECK (username = lower(username) AND length(username) BETWEEN 1 AND 64),
    password_hash text        NOT NULL,
    role          text        NOT NULL CHECK (role IN ('admin')),
    disabled      boolean     NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- The session id is the SHA-256 of the cookie value: a database leak does not
-- leak usable session tokens.
CREATE TABLE sessions (
    id           text        PRIMARY KEY,
    user_id      uuid        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    csrf_token   text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz,
    ip           text,
    user_agent   text
);
CREATE INDEX sessions_user ON sessions (user_id);

CREATE TABLE audit_log (
    id     bigserial   PRIMARY KEY,
    at     timestamptz NOT NULL DEFAULT now(),
    actor  text,
    action text        NOT NULL,
    target text,
    ip     text,
    detail jsonb       NOT NULL DEFAULT '{}'
);
CREATE INDEX audit_log_recent ON audit_log (action, at);
