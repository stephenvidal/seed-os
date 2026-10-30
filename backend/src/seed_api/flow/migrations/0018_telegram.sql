-- Telegram gateway (M8, D-031): when a notification was sent to Telegram. Only
-- recent unsent ones are sent, so this index stays small.
ALTER TABLE notifications ADD COLUMN telegram_sent_at timestamptz;
CREATE INDEX notifications_telegram_unsent ON notifications (owner, created_at)
    WHERE telegram_sent_at IS NULL;
