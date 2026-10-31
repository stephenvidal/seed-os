-- Test-verified completion (M9, D-038): a command the owner wrote on the task, run in
-- the task's workspace after the agent says it is done, and what came of running it.
ALTER TABLE tasks ADD COLUMN check_command text;
ALTER TABLE tasks ADD COLUMN verification jsonb;
