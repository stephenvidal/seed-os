-- Approvals (M4): a task waits for a person while a tool call needs their decision.
ALTER TABLE tasks DROP CONSTRAINT tasks_state_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_state_check
    CHECK (state IN ('queued', 'running', 'waiting', 'completed', 'failed', 'canceled'));

-- The call waiting for a decision ({id, name, arguments}); set only while waiting.
ALTER TABLE tasks ADD COLUMN awaiting_approval jsonb;
-- Decisions so far, by tool call id: {"<call id>": {"approved": bool, "by": text, "at": text}}.
ALTER TABLE tasks ADD COLUMN approvals jsonb NOT NULL DEFAULT '{}';
ALTER TABLE tasks ADD CONSTRAINT tasks_waiting_has_call
    CHECK ((state = 'waiting') = (awaiting_approval IS NOT NULL));

DROP INDEX tasks_unfinished_turns;
CREATE INDEX tasks_unfinished_turns ON tasks (conversation_id)
    WHERE conversation_id IS NOT NULL AND state IN ('queued', 'running', 'waiting');
