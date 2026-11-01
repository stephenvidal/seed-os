-- Discord gateway (M9, D-044): when a notification was sent to Discord. Only recent
-- unsent ones are sent, so this index stays small.
ALTER TABLE notifications ADD COLUMN discord_sent_at timestamptz;
CREATE INDEX notifications_discord_unsent ON notifications (owner, created_at)
    WHERE discord_sent_at IS NULL;
-- Per Discord user SEED talks to: the direct-message channel, the conversation its
-- messages continue, the turn whose answer is owed, and the approval it was told of.
CREATE TABLE discord_chats (
    user_id         text PRIMARY KEY,
    channel_id      text NOT NULL,
    conversation_id uuid REFERENCES conversations (id) ON DELETE SET NULL,
    awaiting_task   uuid REFERENCES tasks (id) ON DELETE SET NULL,
    told_call       text,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
