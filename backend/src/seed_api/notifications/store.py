"""Notifications (D-030): short records of things a person should hear about without
watching: a task finished or failed, a task waits for an approval, a schedule skipped
a run. `notify` is called inside the transaction that made the change, so a
notification exists exactly when the change committed."""

import uuid
from datetime import datetime
from typing import Literal

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from pydantic import BaseModel

from ..flow.db import Pool

Kind = Literal["task_completed", "task_failed", "approval_needed", "schedule_skipped"]
BODY_CHARS = 300


class Notification(BaseModel):
    id: uuid.UUID
    kind: Kind
    title: str
    body: str
    task_id: uuid.UUID | None
    schedule_id: uuid.UUID | None
    created_at: datetime
    read_at: datetime | None


def brief(text: str | None) -> str:
    """The start of `text` on one line, cut to fit a notification."""
    one = " ".join((text or "").split())
    return one if len(one) <= BODY_CHARS else one[: BODY_CHARS - 1] + "…"


async def notify(
    conn: AsyncConnection[DictRow],
    owner: str,
    kind: Kind,
    title: str,
    body: str = "",
    *,
    task_id: uuid.UUID | None = None,
    schedule_id: uuid.UUID | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO notifications (owner, kind, title, body, task_id, schedule_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (owner, kind, title[:200], brief(body), task_id, schedule_id),
    )


class NotificationStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def recent(self, owner: str, *, limit: int, unread_only: bool) -> list[Notification]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM notifications WHERE owner = %s AND (NOT %s OR read_at IS NULL) "
                "ORDER BY created_at DESC, id LIMIT %s",
                (owner, unread_only, limit),
            )
            return [Notification(**r) for r in await cur.fetchall()]

    async def unread(self, owner: str) -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*)::int AS n FROM notifications WHERE owner = %s AND read_at IS NULL",
                (owner,),
            )
            row = await cur.fetchone()
            assert row is not None  # noqa: S101 - count(*) always yields a row
            return int(row["n"])

    async def mark_read(self, owner: str, notification_id: uuid.UUID) -> bool:
        """False when the owner has no such notification. Reading one twice is fine."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE notifications SET read_at = coalesce(read_at, now()) "
                "WHERE id = %s AND owner = %s RETURNING id",
                (notification_id, owner),
            )
            return await cur.fetchone() is not None

    async def mark_all_read(self, owner: str) -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE notifications SET read_at = now() "
                "WHERE owner = %s AND read_at IS NULL RETURNING id",
                (owner,),
            )
            return len(await cur.fetchall())
