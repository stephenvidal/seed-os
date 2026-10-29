-- Tool usage (M8, D-028): the Tools page counts recorded tool results in a time
-- window. Only those events are indexed; text deltas are most of the table.
CREATE INDEX task_events_tool_results ON task_events (created_at) WHERE type = 'tool_result';
