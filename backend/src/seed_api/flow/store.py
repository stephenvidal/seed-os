"""Task persistence and the task state machine.

States: queued → running → completed | failed | canceled, and running → waiting →
queued while a tool call waits for a person's approval or for a delegated task
(D-025): a child task that names its parent. When a child ends, however it ends,
its result is handed to the parent in the same transaction and the parent is
queued to carry on; canceling a parent cancels its children. A running task is held
by a worker lease that the worker must keep extending (heartbeat). Every write a
worker makes is fenced on (lease_owner, attempt, state = running), so a worker
that lost its lease cannot touch a task another worker has since claimed.

Every transition appends to `task_events` in the same transaction, with a
per-task monotonic sequence, so the event log is the task's audit timeline.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from ..agents.store import AgentCopy
from ..core.agent import Checkpoint, DelegatedResult
from ..core.messages import ToolCall, Usage
from ..notifications.store import notify
from .db import Pool

TaskState = Literal["queued", "running", "waiting", "completed", "failed", "canceled"]
TERMINAL: frozenset[str] = frozenset({"completed", "failed", "canceled"})


class ContextMessage(BaseModel):
    """One earlier message of a conversation, as a chat turn's task carries it."""

    role: Literal["user", "assistant"]
    content: str


class Verification(BaseModel):
    """What running a task's check came to (D-038). The exit code decides: `passed`
    is exit code 0 and nothing else. `exit_code` is None when the command was killed
    or could not be run, and `stderr` then says why."""

    command: str
    passed: bool
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    duration_ms: int


class Decision(BaseModel):
    approved: bool
    by: str
    at: datetime


class Task(BaseModel):
    id: uuid.UUID
    created_by: str
    title: str
    model: str
    prompt: str
    state: TaskState
    idempotency_key: str | None
    attempt: int
    max_attempts: int
    cancel_requested: bool
    lease_owner: str | None
    lease_expires_at: datetime | None
    checkpoint: Checkpoint | None
    termination: str | None
    error: str | None
    result_text: str | None
    usage: Usage
    last_seq: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    conversation_id: uuid.UUID | None
    turn: int | None
    parent_id: uuid.UUID | None
    context: list[ContextMessage]
    # Copied from the project when the turn was sent (D-017, D-018).
    project_id: uuid.UUID | None
    instructions: str | None
    memory: str | None
    # Session summaries (D-022): the newest completed turn left out of `context`,
    # whose summary the run gets, and this turn's own summary once a later turn
    # needed it.
    summary_of: uuid.UUID | None
    summary: str | None
    workspace_id: uuid.UUID | None
    awaiting_approval: ToolCall | None
    approvals: dict[str, Decision]
    # D-038: the owner's check, run after the agent finishes, and its result.
    check_command: str | None
    verification: Verification | None
    # Delegation (D-025). On a child: its parent, the parent's call it answers and
    # the agent it runs as. On a parent: the call waiting for a child, and the
    # results children came back with, by call id.
    parent_task_id: uuid.UUID | None
    delegated_call: str | None
    agent: AgentCopy | None
    awaiting_delegation: ToolCall | None
    delegations: dict[str, DelegatedResult]
    # How many delegations deep: 0 for a task a person started (D-026).
    delegation_depth: int

    @property
    def workspace(self) -> uuid.UUID:
        """The id the task's files live under: its conversation's, or its own."""
        return self.workspace_id or self.id


class TaskEvent(BaseModel):
    seq: int
    attempt: int
    type: str
    data: dict[str, Any]
    created_at: datetime


class Lease(BaseModel):
    task_id: uuid.UUID
    worker_id: str
    attempt: int


class Delegation(BaseModel):
    """An agent task to start for a delegate call (D-025)."""

    call: ToolCall
    agent: AgentCopy
    prompt: str
    # What the task is about, for its title.
    about: str


class LeaseLost(Exception):
    """The worker no longer holds the task: its lease expired and was reclaimed,
    or the task was finished elsewhere. The worker must stop without writing."""


# Every worker write is conditional on still holding the lease (see module doc):
# WHERE id = %(id)s AND lease_owner = %(worker)s AND attempt = %(attempt)s AND state = 'running'
def _fence(lease: Lease) -> dict[str, Any]:
    return {"id": lease.task_id, "worker": lease.worker_id, "attempt": lease.attempt}


async def _log(
    conn: AsyncConnection[DictRow], row: DictRow, type_: str, data: dict[str, Any]
) -> None:
    """Record an event for a row whose UPDATE already advanced last_seq."""
    await conn.execute(
        "INSERT INTO task_events (task_id, seq, attempt, type, data) VALUES (%s, %s, %s, %s, %s)",
        (row["id"], row["last_seq"], row["attempt"], type_, Jsonb(data)),
    )


async def insert_task(
    conn: AsyncConnection[DictRow],
    *,
    created_by: str,
    title: str,
    model: str,
    prompt: str,
    max_attempts: int,
    idempotency_key: str | None,
    conversation_id: uuid.UUID | None = None,
    turn: int | None = None,
    parent_id: uuid.UUID | None = None,
    context: list[ContextMessage] | None = None,
    project_id: uuid.UUID | None = None,
    instructions: str | None = None,
    memory: str | None = None,
    summary_of: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    parent_task_id: uuid.UUID | None = None,
    delegated_call: str | None = None,
    agent: AgentCopy | None = None,
    delegation_depth: int = 0,
    check_command: str | None = None,
) -> DictRow | None:
    """Insert a queued task and its first event. Returns None, inserting nothing,
    when this creator already used the idempotency key. Call inside a transaction."""
    cur = await conn.execute(
        """
        INSERT INTO tasks (id, created_by, title, model, prompt, state, idempotency_key,
                           max_attempts, last_seq, conversation_id, turn, parent_id, context,
                           workspace_id, project_id, instructions, memory, summary_of,
                           parent_task_id, delegated_call, agent, delegation_depth,
                           check_command)
        VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s)
        ON CONFLICT (created_by, idempotency_key) DO NOTHING
        RETURNING *
        """,
        (
            uuid.uuid4(),
            created_by,
            title,
            model,
            prompt,
            idempotency_key,
            max_attempts,
            conversation_id,
            turn,
            parent_id,
            Jsonb([m.model_dump() for m in context or []]),
            workspace_id or conversation_id,
            project_id,
            instructions,
            memory,
            summary_of,
            parent_task_id,
            delegated_call,
            Jsonb(agent.model_dump(mode="json")) if agent else None,
            delegation_depth,
            check_command,
        ),
    )
    row = await cur.fetchone()
    if row is not None:
        data: dict[str, Any] = {"model": model, "title": title}
        if conversation_id is not None:
            data |= {"conversation_id": str(conversation_id), "turn": turn}
        if parent_task_id is not None and agent is not None:
            data |= {"parent_task_id": str(parent_task_id), "agent": agent.name}
        await _log(conn, row, "task_created", data)
    return row


async def task_by_key(
    conn: AsyncConnection[DictRow], created_by: str, idempotency_key: str | None
) -> Task | None:
    cur = await conn.execute(
        "SELECT * FROM tasks WHERE created_by = %s AND idempotency_key = %s",
        (created_by, idempotency_key),
    )
    row = await cur.fetchone()
    return Task.model_validate(row) if row else None


class TaskStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    # --- API side -------------------------------------------------------------

    async def create(
        self,
        *,
        created_by: str,
        title: str,
        model: str,
        prompt: str,
        max_attempts: int,
        idempotency_key: str | None,
        project_id: uuid.UUID | None = None,
        instructions: str | None = None,
        memory: str | None = None,
        check_command: str | None = None,
    ) -> tuple[Task, bool]:
        """Insert a queued task, in a project when `project_id` is given (with what
        it copies from the project, see chat/store.py project_context). With an
        idempotency key already used by this creator, returns the existing task and
        False instead."""
        async with self.pool.connection() as conn, conn.transaction():
            row = await insert_task(
                conn,
                created_by=created_by,
                title=title,
                model=model,
                prompt=prompt,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
                project_id=project_id,
                instructions=instructions,
                memory=memory,
                check_command=check_command,
            )
            if row is not None:
                return Task.model_validate(row), True
            existing = await task_by_key(conn, created_by, idempotency_key)
            if existing is None:  # pragma: no cover - the conflict implies the row exists
                raise RuntimeError("idempotency conflict without an existing task")
            return existing, False

    async def get(self, task_id: uuid.UUID) -> Task | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = await cur.fetchone()
        return Task.model_validate(row) if row else None

    async def list_tasks(
        self, *, limit: int, state: TaskState | None = None, project_id: uuid.UUID | None = None
    ) -> list[Task]:
        """Newest first. With `project_id`, only the project's tasks started outside
        a chat (its chats' turns are listed with the chats)."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM tasks WHERE (%(state)s::text IS NULL OR state = %(state)s) "
                "AND (%(project)s::uuid IS NULL "
                "     OR (project_id = %(project)s AND conversation_id IS NULL)) "
                "ORDER BY created_at DESC, id LIMIT %(limit)s",
                {"state": state, "limit": limit, "project": project_id},
            )
            rows = await cur.fetchall()
        return [Task.model_validate(r) for r in rows]

    async def events(self, task_id: uuid.UUID, *, after: int, limit: int) -> list[TaskEvent]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT seq, attempt, type, data, created_at FROM task_events "
                "WHERE task_id = %s AND seq > %s ORDER BY seq LIMIT %s",
                (task_id, after, limit),
            )
            rows = await cur.fetchall()
        return [TaskEvent.model_validate(r) for r in rows]

    async def request_cancel(self, task_id: uuid.UUID) -> Task | None:
        """Queued and waiting tasks are canceled at once; running ones are flagged
        for their worker. The tasks it delegated to are canceled with it. Returns
        None when the task is missing or already finished."""
        async with self.pool.connection() as conn, conn.transaction():
            row = await _cancel(conn, task_id)
            if row is None:
                return None
            parents = [task_id]
            while parents:  # its children, their children, and so on
                cur = await conn.execute(
                    "SELECT id FROM tasks WHERE parent_task_id = ANY(%s) "
                    "AND state IN ('queued', 'running', 'waiting')",
                    (parents,),
                )
                parents = [r["id"] for r in await cur.fetchall()]
                for child in parents:
                    await _cancel(conn, child)
        return Task.model_validate(row)

    async def retry(self, task_id: uuid.UUID, *, extra_attempts: int) -> Task | None:
        """Re-queue a failed or canceled task as a fresh run (the checkpoint is
        dropped). Returns None when the task is missing or not retryable: a
        delegated task (its parent already has its result and delegates again if
        it needs to), and a chat turn while another turn of its conversation is unfinished:
        turns share a workspace, so two of them must never run at once."""
        async with self.pool.connection() as conn, conn.transaction():
            # The same lock a new turn takes (chat store), so the check below holds.
            await conn.execute(
                "SELECT 1 FROM conversations WHERE id = "
                "(SELECT conversation_id FROM tasks WHERE id = %s) FOR UPDATE",
                (task_id,),
            )
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    state = 'queued', max_attempts = attempt + %s, cancel_requested = false,
                    checkpoint = NULL, termination = NULL, error = NULL, result_text = NULL,
                    verification = NULL, approvals = '{}', delegations = '{}', finished_at = NULL,
                    last_seq = last_seq + 1,
                    updated_at = now()
                WHERE id = %s AND state IN ('failed', 'canceled') AND parent_task_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM tasks other
                      WHERE other.conversation_id = tasks.conversation_id
                        AND other.state IN ('queued', 'running', 'waiting'))
                RETURNING *
                """,
                (extra_attempts, task_id),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            await _log(conn, row, "task_requeued", {"max_attempts": row["max_attempts"]})
        return Task.model_validate(row)

    async def decide(
        self, task_id: uuid.UUID, *, call_id: str, approved: bool, by: str
    ) -> Task | None:
        """Record a person's decision on the call a waiting task waits for and queue
        the task to resume. Returns None when the task is not waiting on that call."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    state = 'queued', awaiting_approval = NULL,
                    approvals = approvals || jsonb_build_object(
                        %(call)s::text,
                        jsonb_build_object('approved', %(ok)s::boolean, 'by', %(by)s::text,
                                           'at', now())),
                    last_seq = last_seq + 1, updated_at = now()
                WHERE id = %(id)s AND state = 'waiting' AND awaiting_approval->>'id' = %(call)s
                RETURNING *
                """,
                {"id": task_id, "call": call_id, "ok": approved, "by": by},
            )
            row = await cur.fetchone()
            if row is None:
                return None
            await _log(
                conn, row, "approval_decided", {"id": call_id, "approved": approved, "by": by}
            )
        return Task.model_validate(row)

    # --- Worker side ----------------------------------------------------------

    async def sweep(self) -> int:
        """Settle running tasks whose lease expired and that must not be retried:
        cancel requested, or no attempts left (dead letter). Returns how many."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    state = CASE WHEN cancel_requested THEN 'canceled' ELSE 'failed' END,
                    termination = CASE WHEN cancel_requested THEN 'cancelled' ELSE 'abandoned' END,
                    error = CASE WHEN cancel_requested THEN NULL
                        ELSE 'The worker stopped responding on every allowed attempt.' END,
                    lease_owner = NULL, lease_expires_at = NULL, finished_at = now(),
                    last_seq = last_seq + 1, updated_at = now()
                WHERE state = 'running' AND lease_expires_at < now()
                  AND (cancel_requested OR attempt >= max_attempts)
                RETURNING *
                """
            )
            rows = await cur.fetchall()
            for row in rows:
                await _log(
                    conn, row, "lease_expired", {"state": row["state"], "attempt": row["attempt"]}
                )
                await _ended(conn, row)
        return len(rows)

    async def claim(self, worker_id: str, lease_s: float) -> tuple[Task, Lease] | None:
        """Take the oldest queued task, or a running one whose worker vanished."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    state = 'running', attempt = attempt + 1, lease_owner = %(worker)s,
                    lease_expires_at = now() + make_interval(secs => %(lease)s),
                    started_at = coalesce(started_at, now()),
                    last_seq = last_seq + 1, updated_at = now()
                WHERE id = (
                    SELECT id FROM tasks
                    WHERE (state = 'queued'
                           OR (state = 'running' AND lease_expires_at < now()))
                      AND NOT cancel_requested AND attempt < max_attempts
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """,
                {"worker": worker_id, "lease": lease_s},
            )
            row = await cur.fetchone()
            if row is None:
                return None
            await _log(
                conn,
                row,
                "attempt_started",
                {
                    "attempt": row["attempt"],
                    "worker": worker_id,
                    "resumed_at_step": (row["checkpoint"] or {}).get("steps"),
                },
            )
        task = Task.model_validate(row)
        return task, Lease(task_id=task.id, worker_id=worker_id, attempt=task.attempt)

    async def heartbeat(self, lease: Lease, lease_s: float) -> bool:
        """Extend the lease. Returns whether cancellation was requested."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE tasks SET lease_expires_at = now() + make_interval(secs => %(lease)s) "
                "WHERE id = %(id)s AND lease_owner = %(worker)s AND attempt = %(attempt)s "
                "AND state = 'running' RETURNING cancel_requested",
                {**_fence(lease), "lease": lease_s},
            )
            row = await cur.fetchone()
        if row is None:
            raise LeaseLost(str(lease.task_id))
        return bool(row["cancel_requested"])

    async def usage_since(self, since: datetime) -> dict[str, Usage]:
        """Tokens by model of every task touched since then, running ones included
        (a running task's usage is saved at each checkpoint)."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT model,
                       coalesce(sum((usage->>'input_tokens')::bigint), 0)::bigint AS i,
                       coalesce(sum((usage->>'output_tokens')::bigint), 0)::bigint AS o
                FROM tasks WHERE updated_at >= %(since)s GROUP BY model
                """,
                {"since": since},
            )
            return {
                r["model"]: Usage(input_tokens=r["i"], output_tokens=r["o"])
                for r in await cur.fetchall()
            }

    async def append_event(self, lease: Lease, type_: str, data: dict[str, Any]) -> int:
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE tasks SET last_seq = last_seq + 1 "
                "WHERE id = %(id)s AND lease_owner = %(worker)s AND attempt = %(attempt)s "
                "AND state = 'running' RETURNING *",
                _fence(lease),
            )
            row = await cur.fetchone()
            if row is None:
                raise LeaseLost(str(lease.task_id))
            await _log(conn, row, type_, data)
        return int(row["last_seq"])

    async def save_checkpoint(self, lease: Lease, checkpoint: Checkpoint) -> None:
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE tasks SET checkpoint = %(cp)s, usage = %(usage)s, updated_at = now(), "
                "last_seq = last_seq + 1 "
                "WHERE id = %(id)s AND lease_owner = %(worker)s AND attempt = %(attempt)s "
                "AND state = 'running' RETURNING *",
                {
                    **_fence(lease),
                    "cp": Jsonb(checkpoint.model_dump(mode="json")),
                    "usage": Jsonb(checkpoint.usage.model_dump()),
                },
            )
            row = await cur.fetchone()
            if row is None:
                raise LeaseLost(str(lease.task_id))
            # Recorded so the inspector can show where a retry would resume.
            await _log(
                conn,
                row,
                "checkpoint_saved",
                {"steps": checkpoint.steps, "pending": len(checkpoint.pending)},
            )

    async def finish(
        self,
        lease: Lease,
        *,
        state: Literal["completed", "failed", "canceled"],
        termination: str,
        error: str | None,
        result_text: str,
        usage: Usage,
        verification: Verification | None = None,
    ) -> None:
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    state = %(state)s, termination = %(term)s, error = %(error)s,
                    result_text = %(text)s, usage = %(usage)s,
                    verification = coalesce(%(verification)s::jsonb, verification),
                    lease_owner = NULL, lease_expires_at = NULL,
                    finished_at = now(), updated_at = now()
                WHERE id = %(id)s AND lease_owner = %(worker)s AND attempt = %(attempt)s
                  AND state = 'running'
                RETURNING *
                """,
                {
                    **_fence(lease),
                    "state": state,
                    "term": termination,
                    "error": error,
                    "text": result_text,
                    "usage": Jsonb(usage.model_dump()),
                    "verification": Jsonb(verification.model_dump()) if verification else None,
                },
            )
            row = await cur.fetchone()
            if row is None:
                raise LeaseLost(str(lease.task_id))
            await _ended(conn, row)

    async def pause(self, lease: Lease, call: ToolCall) -> None:
        """Park a running task until a person decides on `call`. The attempt is not
        counted: the run resumes from its checkpoint once the task is queued again.
        The run itself already logged approval_requested."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    state = 'waiting', awaiting_approval = %(call)s, attempt = attempt - 1,
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
                WHERE id = %(id)s AND lease_owner = %(worker)s AND attempt = %(attempt)s
                  AND state = 'running'
                RETURNING *
                """,
                {**_fence(lease), "call": Jsonb(call.model_dump(mode="json"))},
            )
            row = await cur.fetchone()
            if row is None:
                raise LeaseLost(str(lease.task_id))
            # An agent task's approval is asked of the person too: nobody else can decide.
            if row["conversation_id"] is None:
                await notify(
                    conn,
                    row["created_by"],
                    "approval_needed",
                    row["title"],
                    f"Waiting for your approval to call {call.name}.",
                    task_id=row["id"],
                )

    async def delegation_status(self, task_id: uuid.UUID) -> tuple[set[str], set[str]]:
        """The delegate calls of a task's current run that have an agent task still
        working, and those that already have a result (D-026)."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT
                    ARRAY(SELECT delegated_call FROM tasks c
                          WHERE c.parent_task_id = t.id
                            AND c.state IN ('queued', 'running', 'waiting')) AS active,
                    ARRAY(SELECT jsonb_object_keys(t.delegations)) AS answered
                FROM tasks t WHERE t.id = %s
                """,
                (task_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return set(), set()
        return set(row["active"]), set(row["answered"])

    async def delegate(
        self,
        lease: Lease,
        *,
        starts: list[Delegation],
        refusals: list[tuple[ToolCall, str]],
        wait_for: ToolCall,
    ) -> list[uuid.UUID]:
        """Start an agent task for each of `starts`, answer each of `refusals` with
        its reason, and park the running task until `wait_for` has a result (or
        queue it at once when it already has one). One transaction (D-025, D-026).
        Each child works in the parent's workspace and project, one level deeper,
        with the agent's model or else the parent's. Returns the children's ids."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM tasks WHERE id = %(id)s AND lease_owner = %(worker)s "
                "AND attempt = %(attempt)s AND state = 'running' FOR UPDATE",
                _fence(lease),
            )
            parent = await cur.fetchone()
            if parent is None:
                raise LeaseLost(str(lease.task_id))
            events: list[tuple[str, dict[str, Any]]] = []
            children: list[uuid.UUID] = []
            for d in starts:
                child = await insert_task(
                    conn,
                    created_by=parent["created_by"],
                    title=f"{d.agent.name}: {' '.join(d.about.split())[:70]}",
                    model=d.agent.model or parent["model"],
                    prompt=d.prompt,
                    max_attempts=parent["max_attempts"],
                    idempotency_key=None,
                    workspace_id=parent["workspace_id"] or parent["id"],
                    project_id=parent["project_id"],
                    parent_task_id=parent["id"],
                    delegated_call=d.call.id,
                    agent=d.agent,
                    delegation_depth=parent["delegation_depth"] + 1,
                )
                assert child is not None  # noqa: S101 - no idempotency key, so no conflict
                children.append(child["id"])
                events.append(
                    (
                        "delegated",
                        {"id": d.call.id, "agent": d.agent.name, "task_id": str(child["id"])},
                    )
                )
            answers: dict[str, Any] = {}
            for call, reason in refusals:
                result = DelegatedResult(ok=False, content=json.dumps({"error": reason}))
                answers[call.id] = result.model_dump()
                events.append(("delegation_refused", {"id": call.id, "reason": reason}))
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    delegations = delegations || %(answers)s,
                    state = CASE WHEN delegations || %(answers)s ? %(wait)s
                                 THEN 'queued' ELSE 'waiting' END,
                    awaiting_delegation = CASE WHEN delegations || %(answers)s ? %(wait)s
                                               THEN NULL ELSE %(call)s END,
                    attempt = attempt - 1, lease_owner = NULL, lease_expires_at = NULL,
                    last_seq = last_seq + %(n)s, updated_at = now()
                WHERE id = %(id)s
                RETURNING *
                """,
                {
                    "id": parent["id"],
                    "answers": Jsonb(answers),
                    "wait": wait_for.id,
                    "call": Jsonb(wait_for.model_dump(mode="json")),
                    "n": len(events),
                },
            )
            row = await cur.fetchone()
            assert row is not None  # noqa: S101 - the row is locked above
            first = row["last_seq"] - len(events)
            for i, (type_, data) in enumerate(events, start=1):
                await _log(conn, {**row, "last_seq": first + i}, type_, data)
        return children

    async def release(self, lease: Lease) -> None:
        """Hand a task back on graceful shutdown. The attempt is not counted, and
        the checkpoint is kept so the next worker resumes from it."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    state = 'queued', attempt = attempt - 1, lease_owner = NULL,
                    lease_expires_at = NULL, last_seq = last_seq + 1, updated_at = now()
                WHERE id = %(id)s AND lease_owner = %(worker)s AND attempt = %(attempt)s
                  AND state = 'running'
                RETURNING *
                """,
                _fence(lease),
            )
            row = await cur.fetchone()
            if row is None:
                raise LeaseLost(str(lease.task_id))
            await _log(conn, row, "task_released", {"reason": "worker_shutdown"})


async def _cancel(conn: AsyncConnection[DictRow], task_id: uuid.UUID) -> DictRow | None:
    """Cancel one unfinished task (see request_cancel) and report it to its parent."""
    cur = await conn.execute(
        """
        UPDATE tasks SET
            cancel_requested = true,
            state = CASE WHEN state = 'running' THEN state ELSE 'canceled' END,
            termination = CASE WHEN state = 'running' THEN termination ELSE 'cancelled' END,
            finished_at = CASE WHEN state = 'running' THEN finished_at ELSE now() END,
            awaiting_approval = NULL,
            awaiting_delegation = NULL,
            last_seq = last_seq + 1,
            updated_at = now()
        WHERE id = %s AND state IN ('queued', 'running', 'waiting')
        RETURNING *
        """,
        (task_id,),
    )
    row = await cur.fetchone()
    if row is not None:
        await _log(conn, row, "cancel_requested", {"state": row["state"]})
        await _ended(conn, row)
    return row


# What a parent's model reads of a child's work (D-025).
RESULT_CHARS = 20_000

_RESULT_TEXT = {
    "failed": "The task failed",
    "canceled": "The task was canceled",
}


def _worth_telling(row: DictRow) -> bool:
    """A task a person started on its own: not a chat turn they are reading as it
    runs, and not an agent task, whose result goes to its parent."""
    return row["conversation_id"] is None and row["parent_task_id"] is None


async def _ended(conn: AsyncConnection[DictRow], row: DictRow) -> None:
    """After a task's state changed: when it has ended, report it to its parent and
    cancel the agent tasks it still has running, as nothing would read their
    results (D-026). Call in the transaction that changed the task."""
    if row["state"] not in TERMINAL:
        return
    if _worth_telling(row) and row["state"] != "canceled":
        done = row["state"] == "completed"
        await notify(
            conn,
            row["created_by"],
            "task_completed" if done else "task_failed",
            row["title"],
            (row["result_text"] if done else row["error"]) or "",
            task_id=row["id"],
        )
    await _report_to_parent(conn, row)
    cur = await conn.execute(
        "SELECT id FROM tasks WHERE parent_task_id = %s "
        "AND state IN ('queued', 'running', 'waiting')",
        (row["id"],),
    )
    for child in await cur.fetchall():
        await _cancel(conn, child["id"])


async def _report_to_parent(conn: AsyncConnection[DictRow], child: DictRow) -> None:
    """Hand an ended child's result to its parent and queue the parent, when the
    parent still waits for it. Call in the transaction that ended the child."""
    if child["parent_task_id"] is None or child["state"] not in TERMINAL:
        return
    agent = (child["agent"] or {}).get("name")
    ok = child["state"] == "completed"
    body: dict[str, Any] = {"agent": agent, "task_id": str(child["id"]), "state": child["state"]}
    if ok:
        body["result"] = (child["result_text"] or "")[:RESULT_CHARS]
    else:
        reason = child["error"] or ""
        body["error"] = f"{_RESULT_TEXT[child['state']]}{': ' + reason if reason else '.'}"
    result = DelegatedResult(ok=ok, content=json.dumps(body, ensure_ascii=False))
    cur = await conn.execute(
        """
        UPDATE tasks SET
            delegations = delegations || jsonb_build_object(%(call)s::text, %(result)s::jsonb),
            state = CASE WHEN awaiting_delegation->>'id' = %(call)s THEN 'queued' ELSE state END,
            awaiting_delegation = CASE WHEN awaiting_delegation->>'id' = %(call)s
                                       THEN NULL ELSE awaiting_delegation END,
            last_seq = last_seq + 1, updated_at = now()
        WHERE id = %(id)s AND state IN ('queued', 'running', 'waiting')
        RETURNING *
        """,
        {
            "id": child["parent_task_id"],
            "call": child["delegated_call"],
            "result": Jsonb(result.model_dump()),
        },
    )
    parent = await cur.fetchone()
    if parent is not None:
        await _log(
            conn,
            parent,
            "delegation_finished",
            {
                "id": child["delegated_call"],
                "task_id": str(child["id"]),
                "agent": agent,
                "state": child["state"],
            },
        )
