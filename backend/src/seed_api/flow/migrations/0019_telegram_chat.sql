-- Chatting with SEED from Telegram (M8, D-032). Per chat: the conversation its
-- messages continue, the turn whose answer is owed, and the approval it was told of.
CREATE TABLE telegram_chats (
    chat_id         bigint PRIMARY KEY,
    conversation_id uuid REFERENCES conversations (id) ON DELETE SET NULL,
    awaiting_task   uuid REFERENCES tasks (id) ON DELETE SET NULL,
    -- The approval call the chat was last told about, so it is told once.
    told_call       text,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
-- The next Bot API update to read, kept so a restart does not read updates again.
CREATE TABLE telegram_offset (
    id          integer PRIMARY KEY CHECK (id = 1),
    next_update bigint NOT NULL
);
