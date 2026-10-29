"""Overview API: what is running, what needs a person, and token use by model,
read straight from the task store for the Command Center (M5)."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from pydantic import BaseModel

from .api import AdminOnly, StoreDep, TaskView
from .store import Task

router = APIRouter(prefix="/api/v1/overview", tags=["overview"])


class Counts(BaseModel):
    queued: int
    running: int
    # Waiting for a person's approval.
    waiting: int
    # Waiting for a task they delegated to an agent (D-025).
    delegating: int
    # Tasks that finished within the window, by final state.
    completed: int
    failed: int
    canceled: int


class ModelUsage(BaseModel):
    model: str
    tasks: int
    input_tokens: int
    output_tokens: int


class Overview(BaseModel):
    window_hours: int
    generated_at: datetime
    counts: Counts
    # Waiting for a person's approval (all), then failed within the window; newest first.
    attention: list[TaskView]
    # Running, then queued; oldest first, as the workers take them.
    active: list[TaskView]
    # Completed within the window, newest first.
    recent: list[TaskView]
    # Tokens of tasks that finished within the window, by model, most used first.
    usage: list[ModelUsage]


async def _tasks(
    conn: AsyncConnection[DictRow], sql: str, params: dict[str, Any]
) -> list[TaskView]:
    cur = await conn.execute(sql, params)
    return [TaskView.of(Task.model_validate(r)) for r in await cur.fetchall()]


@router.get("", response_model=Overview)
async def overview(
    _: AdminOnly,
    store: StoreDep,
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> Overview:
    """A snapshot of all tasks. Counts and usage cover tasks that finished in the
    last `hours`; queued, running and waiting are as of now."""
    async with store.pool.connection() as conn:
        # One clock for the whole snapshot: the database's.
        cur = await conn.execute(
            "SELECT now() AS at, now() - make_interval(hours => %s) AS since", (hours,)
        )
        clock = await cur.fetchone()
        assert clock is not None  # noqa: S101 - a SELECT without FROM yields one row
        p: dict[str, Any] = {"since": clock["since"], "limit": 10}
        cur = await conn.execute(
            """
            SELECT count(*) FILTER (WHERE state = 'queued')::int AS queued,
                   count(*) FILTER (WHERE state = 'running')::int AS running,
                   count(*) FILTER (WHERE awaiting_approval IS NOT NULL)::int AS waiting,
                   count(*) FILTER (WHERE awaiting_delegation IS NOT NULL)::int AS delegating,
                   count(*) FILTER (WHERE state = 'completed' AND finished_at >= %(since)s)::int
                       AS completed,
                   count(*) FILTER (WHERE state = 'failed' AND finished_at >= %(since)s)::int
                       AS failed,
                   count(*) FILTER (WHERE state = 'canceled' AND finished_at >= %(since)s)::int
                       AS canceled
            FROM tasks
            """,
            p,
        )
        counts = await cur.fetchone()
        assert counts is not None  # noqa: S101 - an aggregate always yields a row
        attention = await _tasks(
            conn,
            """
            SELECT * FROM tasks
            WHERE awaiting_approval IS NOT NULL
               OR (state = 'failed' AND finished_at >= %(since)s)
            ORDER BY state = 'waiting' DESC, updated_at DESC, id LIMIT %(limit)s
            """,
            p,
        )
        active = await _tasks(
            conn,
            "SELECT * FROM tasks WHERE state IN ('running', 'queued') "
            "OR awaiting_delegation IS NOT NULL "
            "ORDER BY state = 'running' DESC, created_at, id LIMIT %(limit)s",
            p,
        )
        recent = await _tasks(
            conn,
            "SELECT * FROM tasks WHERE state = 'completed' AND finished_at >= %(since)s "
            "ORDER BY finished_at DESC, id LIMIT 5",
            p,
        )
        cur = await conn.execute(
            """
            SELECT model, count(*)::int AS tasks,
                   coalesce(sum((usage->>'input_tokens')::bigint), 0)::bigint AS input_tokens,
                   coalesce(sum((usage->>'output_tokens')::bigint), 0)::bigint AS output_tokens
            FROM tasks WHERE finished_at >= %(since)s
            GROUP BY model
            ORDER BY sum((usage->>'input_tokens')::bigint + (usage->>'output_tokens')::bigint)
                DESC, model
            """,
            p,
        )
        usage = [ModelUsage.model_validate(r) for r in await cur.fetchall()]
    return Overview(
        window_hours=hours,
        generated_at=clock["at"],
        counts=Counts.model_validate(counts),
        attention=attention,
        active=active,
        recent=recent,
        usage=usage,
    )
