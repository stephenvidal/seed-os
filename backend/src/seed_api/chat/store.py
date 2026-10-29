"""Conversations and their turns. A turn is a task (see flow/store.py) that carries
the conversation so far, so chat replies get leases, checkpoints, recovery and the
event stream for free.

Turns of one conversation run one at a time: they share a workspace, and each
turn's context must include the answer before it. Sending a turn locks the
conversation row and refuses while an earlier turn is unfinished.
"""

import uuid
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from pydantic import BaseModel

from ..flow.db import Pool
from ..flow.store import ContextMessage, Task, insert_task, task_by_key


class Conversation(BaseModel):
    id: uuid.UUID
    owner: str
    title: str
    model: str
    created_at: datetime
    updated_at: datetime


class ConversationSummary(Conversation):
    turns: int
    last_state: str | None


class ChatError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _KeyTaken(Exception):
    """Another request inserted a task with this idempotency key first."""


def context_of(rows: list[DictRow], max_turns: int) -> list[ContextMessage]:
    """The prompts and answers of the last `max_turns` completed turns, oldest
    first. Failed and canceled turns have no answer to carry, so they are left out."""
    done = [r for r in rows if r["state"] == "completed"][-max_turns:]
    out: list[ContextMessage] = []
    for r in done:
        out.append(ContextMessage(role="user", content=r["prompt"]))
        out.append(ContextMessage(role="assistant", content=r["result_text"] or ""))
    return out


def _same_turn(task: Task, conversation_id: uuid.UUID | None, prompt: str) -> Task:
    """An idempotent replay must repeat the original request exactly."""
    if (
        task.conversation_id is None
        or task.prompt != prompt
        or (conversation_id is not None and task.conversation_id != conversation_id)
    ):
        raise ChatError(
            "idempotency_conflict", "This Idempotency-Key was already used for a different message."
        )
    return task


class ChatStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def start(
        self,
        *,
        owner: str,
        model: str,
        prompt: str,
        max_attempts: int,
        idempotency_key: str | None,
    ) -> tuple[Conversation, Task, bool]:
        """Create a conversation with its first turn. A replayed idempotency key
        returns the original conversation and turn, and False."""
        title = " ".join(prompt.split())[:80]
        try:
            async with self.pool.connection() as conn, conn.transaction():
                if idempotency_key is not None:
                    existing = await task_by_key(conn, owner, idempotency_key)
                    if existing is not None:
                        task = _same_turn(existing, None, prompt)
                        conv = await self._get(conn, owner, task.conversation_id)
                        if conv is None:  # pragma: no cover - the turn's FK holds it
                            raise RuntimeError("turn without a conversation")
                        return conv, task, False
                cur = await conn.execute(
                    "INSERT INTO conversations (id, owner, title, model) "
                    "VALUES (%s, %s, %s, %s) RETURNING *",
                    (uuid.uuid4(), owner, title, model),
                )
                conv_row = await cur.fetchone()
                assert conv_row is not None  # noqa: S101 - RETURNING always yields the row
                row = await insert_task(
                    conn,
                    created_by=owner,
                    title=title,
                    model=model,
                    prompt=prompt,
                    max_attempts=max_attempts,
                    idempotency_key=idempotency_key,
                    conversation_id=conv_row["id"],
                    turn=1,
                )
                if row is None:
                    raise _KeyTaken  # roll back the conversation just inserted
                return Conversation.model_validate(conv_row), Task.model_validate(row), True
        except _KeyTaken:
            return await self.start(
                owner=owner,
                model=model,
                prompt=prompt,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
            )

    async def send(
        self,
        conversation_id: uuid.UUID,
        *,
        owner: str,
        prompt: str,
        model: str | None,
        max_attempts: int,
        idempotency_key: str | None,
        context_turns: int,
    ) -> tuple[Task, bool]:
        """Add a turn. Raises ChatError not_found, turn_in_progress or
        idempotency_conflict."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM conversations WHERE id = %s AND owner = %s FOR UPDATE",
                (conversation_id, owner),
            )
            conv = await cur.fetchone()
            if conv is None:
                raise ChatError("not_found", "No such conversation.")
            if idempotency_key is not None:
                existing = await task_by_key(conn, owner, idempotency_key)
                if existing is not None:
                    return _same_turn(existing, conversation_id, prompt), False
            cur = await conn.execute(
                "SELECT turn, prompt, result_text, state FROM tasks "
                "WHERE conversation_id = %s ORDER BY turn",
                (conversation_id,),
            )
            rows = await cur.fetchall()
            if any(r["state"] in ("queued", "running") for r in rows):
                raise ChatError(
                    "turn_in_progress",
                    "The previous message is still being answered. Wait for it, or cancel it.",
                )
            use_model = model or conv["model"]
            row = await insert_task(
                conn,
                created_by=owner,
                title=conv["title"],
                model=use_model,
                prompt=prompt,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
                conversation_id=conversation_id,
                turn=(rows[-1]["turn"] if rows else 0) + 1,
                context=context_of(rows, context_turns),
            )
            if row is None:  # pragma: no cover - the key was checked under the lock
                raise RuntimeError("idempotency key taken under the conversation lock")
            await conn.execute(
                "UPDATE conversations SET model = %s, updated_at = now() WHERE id = %s",
                (use_model, conversation_id),
            )
            return Task.model_validate(row), True

    async def _get(
        self, conn: AsyncConnection[DictRow], owner: str, conversation_id: Any
    ) -> Conversation | None:
        cur = await conn.execute(
            "SELECT * FROM conversations WHERE id = %s AND owner = %s", (conversation_id, owner)
        )
        row = await cur.fetchone()
        return Conversation.model_validate(row) if row else None

    async def get(self, owner: str, conversation_id: uuid.UUID) -> Conversation | None:
        async with self.pool.connection() as conn:
            return await self._get(conn, owner, conversation_id)

    async def turns(self, conversation_id: uuid.UUID) -> list[Task]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM tasks WHERE conversation_id = %s ORDER BY turn", (conversation_id,)
            )
            rows = await cur.fetchall()
        return [Task.model_validate(r) for r in rows]

    async def list(self, owner: str, *, limit: int) -> list[ConversationSummary]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT c.*, count(t.id)::int AS turns,
                       (array_agg(t.state ORDER BY t.turn DESC))[1] AS last_state
                FROM conversations c LEFT JOIN tasks t ON t.conversation_id = c.id
                WHERE c.owner = %s
                GROUP BY c.id
                ORDER BY c.updated_at DESC, c.id
                LIMIT %s
                """,
                (owner, limit),
            )
            rows = await cur.fetchall()
        return [ConversationSummary.model_validate(r) for r in rows]
