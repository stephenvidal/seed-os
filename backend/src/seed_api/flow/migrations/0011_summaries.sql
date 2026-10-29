-- Session summaries (M6, D-022): a chat turn sees its last turns in full; the
-- completed turns before them reach the model as one summary instead of being
-- dropped. `summary` on a turn covers its path from the first message through
-- that turn, so it holds for every version built on it. `summary_of` is fixed
-- when a turn is sent: the newest completed turn left out of its context.
ALTER TABLE tasks
    ADD COLUMN summary    text CHECK (char_length(summary) BETWEEN 1 AND 4000),
    ADD COLUMN summary_of uuid REFERENCES tasks (id) ON DELETE SET NULL;
