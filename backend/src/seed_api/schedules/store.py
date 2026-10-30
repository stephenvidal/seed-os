"""Schedules (D-029): a saved task that starts on a timetable.

A worker calls `fire_due` on every pass. It locks the schedules whose time has come
(`FOR UPDATE SKIP LOCKED`, so workers never fire the same one), starts a task for
each in the same transaction that sets the next run, and records it in the audit
log: a due time starts at most one task, however many workers there are and
however often they poll. A run missed while nothing was running starts once when
the workers are back, not once per missed time. A run is skipped when the task
the schedule started last time is still going.
"""

import uuid
from datetime import UTC, datetime, time
from typing import Any, Literal

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from ..chat.store import ChatError, project_context
from ..flow.db import Pool
from ..flow.store import insert_task
from .recurrence import Kind, next_run

Outcome = Literal["started", "skipped_busy"]
# Tasks that have not finished: a schedule does not start another beside one.
ACTIVE = ("queued", "running", "waiting")
BATCH = 20


class Schedule(BaseModel):
    id: uuid.UUID
    owner: str
    name: str
    prompt: str
    model: str
    project_id: uuid.UUID | None
    kind: Kind
    every_minutes: int | None
    at_time: time | None
    timezone: str
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_outcome: Outcome | None
    last_task_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ScheduleInput(BaseModel):
    """A whole definition: creating and changing a schedule both give all of it."""

    name: str
    prompt: str
    model: str
    project_id: uuid.UUID | None
    kind: Kind
    every_minutes: int | None
    at_time: time | None
    timezone: str
    enabled: bool


class ScheduleStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def all(self, owner: str) -> list[Schedule]:
        """By name."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM schedules WHERE owner = %s ORDER BY lower(name), id", (owner,)
            )
            return [Schedule.model_validate(r) for r in await cur.fetchall()]

    async def get(self, owner: str, schedule_id: uuid.UUID) -> Schedule | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM schedules WHERE id = %s AND owner = %s", (schedule_id, owner)
            )
            row = await cur.fetchone()
        return Schedule.model_validate(row) if row else None

    async def _first_run(self, conn: AsyncConnection[DictRow], s: ScheduleInput) -> datetime | None:
        if not s.enabled:
            return None
        cur = await conn.execute("SELECT now() AS at")
        clock = await cur.fetchone()
        assert clock is not None  # noqa: S101 - a SELECT without FROM yields one row
        return next_run(
            s.kind,
            clock["at"],
            every_minutes=s.every_minutes,
            at_time=s.at_time,
            timezone=s.timezone,
        )

    async def create(self, owner: str, s: ScheduleInput) -> Schedule:
        """Raises ChatError project_not_found."""
        async with self.pool.connection() as conn, conn.transaction():
            await project_context(conn, owner, s.project_id)
            cur = await conn.execute(
                """
                INSERT INTO schedules (id, owner, name, prompt, model, project_id, kind,
                                       every_minutes, at_time, timezone, enabled, next_run_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
                """,
                (
                    uuid.uuid4(),
                    owner,
                    s.name,
                    s.prompt,
                    s.model,
                    s.project_id,
                    s.kind,
                    s.every_minutes,
                    s.at_time,
                    s.timezone,
                    s.enabled,
                    await self._first_run(conn, s),
                ),
            )
            row = await cur.fetchone()
        assert row is not None  # noqa: S101 - RETURNING always yields the row
        return Schedule.model_validate(row)

    async def update(self, schedule_id: uuid.UUID, owner: str, s: ScheduleInput) -> Schedule | None:
        """Replace the definition and work out the next run afresh. None when there
        is no such schedule; raises ChatError project_not_found."""
        async with self.pool.connection() as conn, conn.transaction():
            await project_context(conn, owner, s.project_id)
            cur = await conn.execute(
                """
                UPDATE schedules SET name = %s, prompt = %s, model = %s, project_id = %s,
                       kind = %s, every_minutes = %s, at_time = %s, timezone = %s,
                       enabled = %s, next_run_at = %s, updated_at = now()
                WHERE id = %s AND owner = %s RETURNING *
                """,
                (
                    s.name,
                    s.prompt,
                    s.model,
                    s.project_id,
                    s.kind,
                    s.every_minutes,
                    s.at_time,
                    s.timezone,
                    s.enabled,
                    await self._first_run(conn, s),
                    schedule_id,
                    owner,
                ),
            )
            row = await cur.fetchone()
        return Schedule.model_validate(row) if row else None

    async def delete(self, owner: str, schedule_id: uuid.UUID) -> bool:
        """The tasks it started stay."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM schedules WHERE id = %s AND owner = %s RETURNING id",
                (schedule_id, owner),
            )
            return await cur.fetchone() is not None

    async def run_now(
        self, owner: str, schedule_id: uuid.UUID, max_attempts: int
    ) -> uuid.UUID | None:
        """Start its task now, whatever the timetable says; the timetable is not
        changed. None when there is no such schedule."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM schedules WHERE id = %s AND owner = %s FOR UPDATE",
                (schedule_id, owner),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            task_id = await _start(conn, row, max_attempts, key=None, by="run_now")
            await conn.execute(
                "UPDATE schedules SET last_run_at = now(), last_outcome = 'started', "
                "last_task_id = %s, updated_at = now() WHERE id = %s",
                (task_id, schedule_id),
            )
        return task_id

    async def fire_due(self, max_attempts: int) -> int:
        """Start the tasks of the schedules that are due; returns how many started."""
        started = 0
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT *, now() AS clock FROM schedules "
                "WHERE enabled AND next_run_at <= now() ORDER BY next_run_at "
                "LIMIT %s FOR UPDATE SKIP LOCKED",
                (BATCH,),
            )
            for row in await cur.fetchall():
                due: datetime = row["next_run_at"]
                busy = await _busy(conn, row["last_task_id"])
                task_id = (
                    None
                    if busy
                    else await _start(
                        conn,
                        row,
                        max_attempts,
                        key=f"schedule:{row['id']}:{due.astimezone(UTC).isoformat()}",
                        by="schedule",
                    )
                )
                started += task_id is not None
                nxt = next_run(
                    row["kind"],
                    row["clock"],
                    every_minutes=row["every_minutes"],
                    at_time=row["at_time"],
                    timezone=row["timezone"],
                )
                await conn.execute(
                    """
                    UPDATE schedules SET next_run_at = %s, last_run_at = %s, last_outcome = %s,
                           last_task_id = coalesce(%s, last_task_id), updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        nxt,
                        row["clock"],
                        "skipped_busy" if busy else "started",
                        task_id,
                        row["id"],
                    ),
                )
        return started


async def _busy(conn: AsyncConnection[DictRow], task_id: uuid.UUID | None) -> bool:
    if task_id is None:
        return False
    cur = await conn.execute("SELECT state FROM tasks WHERE id = %s", (task_id,))
    row = await cur.fetchone()
    return row is not None and row["state"] in ACTIVE


async def _start(
    conn: AsyncConnection[DictRow],
    s: dict[str, Any],
    max_attempts: int,
    *,
    key: str | None,
    by: str,
) -> uuid.UUID | None:
    """Insert the schedule's task and record it in the audit log. None when `key`
    was already used: this due time already started its task."""
    try:
        context = await project_context(conn, s["owner"], s["project_id"])
    except ChatError:  # pragma: no cover - the project's deletion removes the schedule
        context = {}
    task = await insert_task(
        conn,
        created_by=s["owner"],
        title=f"Scheduled: {s['name']}"[:200],
        model=s["model"],
        prompt=s["prompt"],
        max_attempts=max_attempts,
        idempotency_key=key,
        **context,
    )
    if task is None:
        return None
    await conn.execute(
        "INSERT INTO audit_log (actor, action, target, detail) VALUES (%s, %s, %s, %s)",
        (
            None if by == "schedule" else s["owner"],
            "schedule_started_task",
            str(s["id"]),
            Jsonb({"task_id": str(task["id"]), "by": by, "owner": s["owner"]}),
        ),
    )
    return uuid.UUID(str(task["id"]))
