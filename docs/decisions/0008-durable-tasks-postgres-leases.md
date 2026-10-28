# ADR-0008 — Durable tasks: Postgres, leased workers, step checkpoints

**Status:** Accepted (2026-10-28)

**Context:** M3 requires tasks that survive refresh, disconnect, worker crash and
server restart, with leases, heartbeats, resume-safe checkpoints, retry policy,
idempotency keys, cancellation, graceful shutdown, recovery, dead-letter and an
audit trail (requirements, "SEED Flow"). ADR-0001 already fixed Postgres and
separate worker processes.

**Options**
1. A job queue library (Celery/RQ/arq) plus Redis next to Postgres.
2. Postgres as the queue: `FOR UPDATE SKIP LOCKED` claims, lease columns, fenced writes.
3. A workflow engine (Temporal and similar).

**Decision:** Option 2.
- Driver: psycopg 3 (async) with a connection pool; plain SQL. Schema changes are
  numbered `.sql` files in `seed_api/flow/migrations`, applied in one transaction
  under an advisory lock by whichever of api/worker starts first.
- States: `queued → running → completed | failed | canceled`. Draft, waiting for
  input and paused are not built until something produces them.
- A worker claims the oldest queued task, or a running task whose lease expired
  (crash recovery), incrementing `attempt`. It renews the lease every lease/3.
  Every worker write is fenced on `(lease_owner, attempt, state = running)`; a
  worker that lost its lease gets `LeaseLost` and stops without writing.
- After each step whose tool calls all have recorded results, the agent loop emits
  a checkpoint (conversation, step count, usage). A recovered task resumes from it;
  step and token limits count across attempts.
- Expired lease with no attempts left → `failed/abandoned` (dead letter). Expired
  lease with cancel requested → `canceled`.
- SIGTERM: the worker interrupts the run and hands the task back (`queued`, attempt
  not counted, checkpoint kept).
- Every transition and run event goes to `task_events` with a per-task monotonic
  `seq`, in the same transaction as the state change. This is the timeline and the
  replay source for ADR-0003.
- Idempotency: optional `Idempotency-Key` on create, unique per creator.

**Reason:** One datastore to operate and back up, and transactional state and
events. SKIP LOCKED is enough for one owner's workload. Option 1 adds a second
stateful service without giving transactional fencing. Option 3 is heavy for a
single-VPS deploy.

**Consequences**
- At-least-once tool execution: a crash between a tool's side effect and the
  checkpoint re-runs that step's tools on resume. Today's only side-effecting tool
  (`write_file`) is an idempotent overwrite. Non-idempotent tools (shell, network,
  messages) must be classified resumable vs. manual-reconcile before they ship.
- One task per worker process; scale by adding processes.
- Each streamed text chunk is one row in `task_events`. That is fine at current
  volume; coalesce if it shows up in profiles.
- Workspaces are per task on the worker's filesystem, so a crash recovery only
  finds earlier files if the same filesystem is shared (true for one worker or a
  shared volume). Artifact storage (M6) replaces this.
