-- Recall across chats (M9, D-039): finished chat turns are searchable by what was
-- asked and answered, so SEED can find what the owner discussed in earlier chats.
ALTER TABLE tasks ADD COLUMN recall_tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', prompt || ' ' || coalesce(result_text, ''))
) STORED;
CREATE INDEX tasks_recall ON tasks USING gin (recall_tsv)
    WHERE conversation_id IS NOT NULL AND state = 'completed';
