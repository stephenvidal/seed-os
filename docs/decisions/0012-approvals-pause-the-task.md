# ADR-0012 — Approvals: the task waits, then resumes from its checkpoint

**Status:** Accepted (2026-10-29)

**Context:** Tool calls that need a person's approval (D-009: shell commands) must
not run until someone decides, and the person may take minutes or hours. Runs
execute in the worker under a lease (ADR-0008); holding a lease, a worker and a
model connection open while waiting would block other tasks and break on restart.

**Options**
1. Keep the run alive in the worker and poll for a decision.
2. End the attempt at the gated call, park the task, and resume from a checkpoint
   once a decision is recorded.

**Decision:** Option 2.

- The agent loop runs a step's tool calls in order. At the first call to a tool
  that `requires_approval` and has no decision, it emits `approval_requested`,
  saves a checkpoint whose `pending` holds that call and the ones after it (none
  of them run), and ends with termination `awaiting_approval`.
- The worker parks the task: state `waiting`, `awaiting_approval` = the call,
  lease released, attempt not counted. Waiting tasks are never claimed.
- `POST /tasks/{id}/decision` records `{approved, by, at}` under the call id in
  `approvals`, only while the task waits on that exact call, then queues the task
  and logs `approval_decided`. Cancel ends a waiting task at once.
- On resume the loop finishes the pending calls first: an approved call runs, a
  denied one gets a `denied` result telling the model not to retry, and a later
  gated call pauses again. Then the loop continues normally.
- The tool registry refuses a gated tool unless the caller passes `approved=True`,
  so nothing outside this path can run it.
- Clients learn of the request from the event stream (`approval_requested` with
  the tool name and arguments), so the Approve/Deny card also survives a reload.

**Consequences:** No resources are held while a task waits. Decisions are audited
with the tool and its arguments. A waiting chat turn counts as unfinished (one turn
at a time). A wait has no timeout; the run's time limit restarts on resume.
