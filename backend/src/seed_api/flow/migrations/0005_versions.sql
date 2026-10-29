-- Chat versions (M4, D-011): editing or regenerating a message adds a sibling turn
-- instead of replacing it, so a conversation is a tree of turns. A turn's parent is
-- the turn before it on its path; `turn` stays its depth (1 = first message).
-- The conversation shows the path from the first message to `head_id`.
ALTER TABLE tasks
    ADD COLUMN parent_id uuid REFERENCES tasks (id) ON DELETE CASCADE,
    DROP CONSTRAINT tasks_turn_unique;

UPDATE tasks t SET parent_id = p.id
FROM tasks p
WHERE t.conversation_id = p.conversation_id AND p.turn = t.turn - 1;

ALTER TABLE tasks
    ADD CONSTRAINT tasks_turn_parent CHECK (
        conversation_id IS NULL AND parent_id IS NULL
        OR conversation_id IS NOT NULL AND (parent_id IS NULL) = (turn = 1)
    );

CREATE INDEX tasks_children ON tasks (parent_id) WHERE parent_id IS NOT NULL;

ALTER TABLE conversations ADD COLUMN head_id uuid REFERENCES tasks (id) ON DELETE SET NULL;

UPDATE conversations c SET head_id = (
    SELECT t.id FROM tasks t WHERE t.conversation_id = c.id ORDER BY t.turn DESC LIMIT 1
);
