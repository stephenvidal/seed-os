# ADR-0013 — Chat: edits and regenerations are versions in a tree of turns

**Status:** Accepted (2026-10-29)

**Context:** M4 asks for edit and regenerate. A turn is a task (ADR-0011) with its
answer, timeline and audit trail. The owner chose (D-011) that editing any message,
or asking it again, keeps the old version and lets the person switch between them.

**Options**
1. Replace the last turn (old one deleted).
2. Replace a turn and drop everything after it.
3. Keep every version: a tree of turns, with one path shown.

**Decision:** Option 3.

- `tasks.parent_id` points at the turn before on the same path (NULL for a first
  message); `turn` is the depth. Versions of a message are turns with the same
  parent. `UNIQUE(conversation_id, turn)` is dropped; a CHECK keeps
  `parent_id IS NULL` exactly for `turn = 1` on chat turns.
- `conversations.head_id` is the last turn of the shown path. Sending a message
  continues from the head and becomes the new head.
- A new version (`POST …/turns/{id}/versions`, with a `prompt` to edit or without
  to regenerate) gets the same parent and the context of the path above it, and
  becomes the head. Older versions and their replies are kept.
- Showing a version (`PUT …/shown`) moves the head to that turn's newest
  descendant, following the newest child at each step.
- The one-unfinished-turn rule spans every version: all of them share the
  conversation's workspace. Showing another version is refused while a turn is
  unfinished, so a turn being answered never drops out of view.
- `GET` returns the shown path; each turn carries the ids of its versions,
  oldest first. Listing reports the shown path's length and last state.
- Migration 0005 links existing turns in order and sets each head to the last.

**Consequences:** Workspace files are not versioned: a version can see files an
older version wrote (artifact versions are M6). Search covers every version.
Deleting a conversation removes every version. The Tasks list shows every version
as its own task.
