# ADR-0011 — Chat: a conversation is a series of tasks

**Status:** Accepted (2026-10-29)

**Context:** M4 needs saved conversations whose replies stream, show their tool
activity and continue. Until now Chat ran the agent inside the HTTP request
(`POST /api/v1/runs`): closing the page stopped it and nothing was stored. Tasks
(ADR-0008) already run in the worker with leases, checkpoints, cancel, retry,
an event log, and a resumable stream (ADR-0003).

**Options**
1. Keep a chat-specific runner and give it its own message store and stream.
2. Run each message as a task that carries the conversation so far.

**Decision:** Option 2.

- `conversations(id, owner, title, model, …)`. A turn is a row in `tasks` with
  `conversation_id` and `turn`; the user's message is the task's prompt and the
  answer is its `result_text`. No separate messages table.
- When a turn is created, the earlier **completed** turns (at most
  `SEED_CHAT_CONTEXT_TURNS`) are copied into the task's `context` column as
  user/assistant messages. The snapshot is fixed, so a resumed or retried
  attempt sees exactly what the first one saw. A resumed attempt continues from
  its checkpoint, which already holds that context.
- `workspace_id` names where a task's files live: the conversation's id for a
  turn, so later messages can use earlier files; the task's own id otherwise.
  The sandbox derives the per-workspace user from it (ADR-0010).
- One unfinished turn per conversation. Sending takes a row lock on the
  conversation and answers 409 `turn_in_progress` while any turn is queued or
  running; retrying a turn takes the same lock and is refused while another turn
  is unfinished. Two turns never share the workspace at once, and every turn's
  context includes the answer before it.
- Clients follow a turn on the existing task stream; the Chat page renders the
  live steps and, once finished, the stored answer as Markdown without raw HTML.

**Consequences:** `POST /api/v1/runs`, its semaphore and
`SEED_MAX_CONCURRENT_RUNS` are removed; concurrency is the number of workers.
Chat turns appear in the Tasks list. Failed or canceled turns stay visible but are
not sent to the model later. Conversation listing is per owner; the Tasks list is
not (open question in D-007). Deleting a conversation, edits, regenerate and
search are later M4 steps.
