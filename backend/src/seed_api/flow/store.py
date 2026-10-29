"""Task persistence and the task state machine.

States: queued → running → completed | failed | canceled, and running → waiting →
queued while a tool call waits for a person's approval. A running task is held
by a worker lease that the worker must keep extending (heartbeat). Every write a
worker makes is fenced on (lease_owner, attempt, state = running), so a worker
that lost its lease cannot touch a task another worker has since claimed.

Every transition appends to `task_events` in the same transaction, with a
per-task monotonic sequence, so the event log is the task's audit timeline.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from ..core.agent import Checkpoint
from ..core.messages import ToolCall, Usage
from .db import Pool

TaskState = Literal["queued", "running", "waiting", "completed", "failed", "canceled"]
TERMINAL: frozenset[str] = frozenset({"completed", "failed", "canceled"})


class ContextMessage(BaseModel):
    """One earlier message of a conversation, as a chat turn's task carries it."""

    role: Literal["user", "assistant"]
    content: str


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
    # The project's instructions when the turn was sent (D-017).
    instructions: str | None
    workspace_id: uuid.UUID | None
    awaiting_approval: ToolCall | None
    approvals: dict[str, Decision]

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
    instructions: str | None = None,
) -> DictRow | None:
    """Insert a queued task and its first event. Returns None, inserting nothing,
    when this creator already used the idempotency key. Call inside a transaction."""
    cur = await conn.execute(
        """
        INSERT INTO tasks (id, created_by, title, model, prompt, state, idempotency_key,
                           max_attempts, last_seq, conversation_id, turn, parent_id, context,
                           workspace_id, instructions)
        VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s, 1, %s, %s, %s, %s, %s, %s)
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
            conversation_id,
            instructions,
        ),
    )
    row = await cur.fetchone()
    if row is not None:
        data: dict[str, Any] = {"model": model, "title": title}
        if conversation_id is not None:
            data |= {"conversation_id": str(conversation_id), "turn": turn}
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
    ) -> tuple[Task, bool]:
        """Insert a queued task. With an idempotency key already used by this
        creator, returns the existing task and False instead."""
        async with self.pool.connection() as conn, conn.transaction():
            row = await insert_task(
                conn,
                created_by=created_by,
                title=title,
                model=model,
                prompt=prompt,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
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

    async def list_tasks(self, *, limit: int, state: TaskState | None = None) -> list[Task]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM tasks WHERE (%(state)s::text IS NULL OR state = %(state)s) "
                "ORDER BY created_at DESC, id LIMIT %(limit)s",
                {"state": state, "limit": limit},
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
        for their worker. Returns None when the task is missing or already finished."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    cancel_requested = true,
                    state = CASE WHEN state = 'running' THEN state ELSE 'canceled' END,
                    termination = CASE WHEN state = 'running' THEN termination ELSE 'cancelled' END,
                    finished_at = CASE WHEN state = 'running' THEN finished_at ELSE now() END,
                    awaiting_approval = NULL,
                    last_seq = last_seq + 1,
                    updated_at = now()
                WHERE id = %s AND state IN ('queued', 'running', 'waiting')
                RETURNING *
                """,
                (task_id,),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            await _log(conn, row, "cancel_requested", {"state": row["state"]})
        return Task.model_validate(row)

    async def retry(self, task_id: uuid.UUID, *, extra_attempts: int) -> Task | None:
        """Re-queue a failed or canceled task as a fresh run (the checkpoint is
        dropped). Returns None when the task is missing or not retryable, which
        includes a chat turn while another turn of its conversation is unfinished:
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
                    approvals = '{}', finished_at = NULL, last_seq = last_seq + 1,
                    updated_at = now()
                WHERE id = %s AND state IN ('failed', 'canceled')
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
    ) -> None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE tasks SET
                    state = %(state)s, termination = %(term)s, error = %(error)s,
                    result_text = %(text)s, usage = %(usage)s,
                    lease_owner = NULL, lease_expires_at = NULL,
                    finished_at = now(), updated_at = now()
                WHERE id = %(id)s AND lease_owner = %(worker)s AND attempt = %(attempt)s
                  AND state = 'running'
                RETURNING id
                """,
                {
                    **_fence(lease),
                    "state": state,
                    "term": termination,
                    "error": error,
                    "text": result_text,
                    "usage": Jsonb(usage.model_dump()),
                },
            )
            if await cur.fetchone() is None:
                raise LeaseLost(str(lease.task_id))

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
                RETURNING id
                """,
                {**_fence(lease), "call": Jsonb(call.model_dump(mode="json"))},
            )
            if await cur.fetchone() is None:
                raise LeaseLost(str(lease.task_id))

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
