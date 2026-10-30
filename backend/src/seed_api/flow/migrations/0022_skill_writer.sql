-- Skills the agent writes (M8, D-033): the task that last wrote a skill, with the
-- owner's approval. NULL: the owner wrote it last.
ALTER TABLE skills ADD COLUMN written_by_task uuid REFERENCES tasks (id) ON DELETE SET NULL;
