-- Delegation limits (M7, D-026): how many delegations deep a task is. 0 for a task
-- a person started; an agent's task is one deeper than the task that delegated it.
ALTER TABLE tasks ADD COLUMN delegation_depth int NOT NULL DEFAULT 0
    CHECK (delegation_depth >= 0);
