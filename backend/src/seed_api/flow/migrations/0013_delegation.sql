-- Delegation (M7, D-025): a task hands a sub-task to an agent as a task of its
-- own. The child names its parent and the parent's tool call it answers, and
-- keeps a copy of the agent's definition as it was when delegated. The parent
-- waits (state 'waiting', `awaiting_delegation` set) until the child ends; the
-- child's result is then added to the parent's `delegations` and it is queued.
ALTER TABLE tasks
    ADD COLUMN parent_task_id      uuid REFERENCES tasks (id) ON DELETE CASCADE,
    ADD COLUMN delegated_call      text,
    ADD COLUMN agent               jsonb,
    ADD COLUMN awaiting_delegation jsonb,
    ADD COLUMN delegations         jsonb NOT NULL DEFAULT '{}';

CREATE INDEX tasks_delegated ON tasks (parent_task_id) WHERE parent_task_id IS NOT NULL;

-- A waiting task waits for exactly one thing: a person's approval or a delegated task.
ALTER TABLE tasks DROP CONSTRAINT tasks_waiting_has_call;
ALTER TABLE tasks ADD CONSTRAINT tasks_waiting_has_call
    CHECK ((state = 'waiting') = (num_nonnulls(awaiting_approval, awaiting_delegation) = 1));
