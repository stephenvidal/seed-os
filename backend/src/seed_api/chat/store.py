"""Conversations and their turns. A turn is a task (see flow/store.py) that carries
the conversation so far, so chat replies get leases, checkpoints, recovery and the
event stream for free.

Turns of one conversation run one at a time: they share a workspace, and each
turn's context must include the answer before it. Sending a turn locks the
conversation row and refuses while an earlier turn is unfinished. Deleting a
conversation takes the same lock and the same refusal, so it never removes a turn
a worker is running.

Editing or regenerating a message adds a version: a sibling turn with the same
parent, so a conversation is a tree (D-011). It shows one path, from the first
message to its head; a new message continues that path, and showing another
version moves the head to the newest turn under it.
"""

import uuid
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from pydantic import BaseModel

from ..flow.db import Pool
from ..flow.store import ContextMessage, Task, insert_task, task_by_key
from ..projects.memory import approved_notes


class Conversation(BaseModel):
    id: uuid.UUID
    owner: str
    title: str
    model: str
    project_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ConversationSummary(Conversation):
    # Of the shown path: its length and its last turn's state.
    turns: int
    last_state: str | None


class Turn(BaseModel):
    """A turn on the shown path, with the ids of all its versions (itself
    included), oldest first."""

    task: Task
    versions: list[uuid.UUID]


class ChatError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


UNFINISHED = ("queued", "running", "waiting")


def _like(text: str) -> str:
    """An ILIKE pattern matching `text` anywhere, with its wildcards taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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


def left_out(rows: list[DictRow], max_turns: int) -> uuid.UUID | None:
    """The newest completed turn too old for `context_of`: the run gets the
    summary of the path through it (D-022). None while every turn fits."""
    done = [r for r in rows if r["state"] == "completed"]
    return done[-max_turns - 1]["id"] if len(done) > max_turns else None


_TREE = (
    "SELECT id, parent_id, turn, prompt, result_text, state, created_at FROM tasks "
    "WHERE conversation_id = %s ORDER BY created_at, id"
)


def path_to(rows: list[DictRow], leaf: uuid.UUID | None) -> list[DictRow]:
    """The turns from the first message down to `leaf`, in order."""
    by_id = {r["id"]: r for r in rows}
    out: list[DictRow] = []
    node = by_id.get(leaf) if leaf is not None else None
    while node is not None:
        out.append(node)
        node = by_id.get(node["parent_id"]) if node["parent_id"] is not None else None
    return out[::-1]


def newest_leaf(rows: list[DictRow], start: uuid.UUID) -> uuid.UUID:
    """Follow the newest child from `start` down to a turn with none. `rows` are
    oldest first, so the last child seen is the newest."""
    newest: dict[uuid.UUID, uuid.UUID] = {}
    for r in rows:
        if r["parent_id"] is not None:
            newest[r["parent_id"]] = r["id"]
    node = start
    while node in newest:
        node = newest[node]
    return node


def _busy(rows: list[DictRow]) -> None:
    if any(r["state"] in UNFINISHED for r in rows):
        raise ChatError(
            "turn_in_progress",
            "The previous message is still being answered. Wait for it, or cancel it.",
        )


async def project_context(
    conn: AsyncConnection[DictRow], owner: str, project_id: uuid.UUID | None
) -> dict[str, Any]:
    """What a new turn copies from its project (insert_task arguments): the
    project, its instructions and its approved memory; nothing outside a project.
    Raises ChatError project_not_found."""
    if project_id is None:
        return {}
    cur = await conn.execute(
        "SELECT instructions FROM projects WHERE id = %s AND owner = %s", (project_id, owner)
    )
    row = await cur.fetchone()
    if row is None:
        raise ChatError("project_not_found", "No such project.")
    return {
        "project_id": project_id,
        "instructions": row["instructions"] or None,
        "memory": await approved_notes(conn, project_id),
    }


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
        project_id: uuid.UUID | None = None,
    ) -> tuple[Conversation, Task, bool]:
        """Create a conversation with its first turn, in a project when
        `project_id` is given. A replayed idempotency key returns the original
        conversation and turn, and False. Raises ChatError project_not_found."""
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
                project = await project_context(conn, owner, project_id)
                cur = await conn.execute(
                    "INSERT INTO conversations (id, owner, title, model, project_id) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING *",
                    (uuid.uuid4(), owner, title, model, project_id),
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
                    **project,
                )
                if row is None:
                    raise _KeyTaken  # roll back the conversation just inserted
                await conn.execute(
                    "UPDATE conversations SET head_id = %s WHERE id = %s",
                    (row["id"], conv_row["id"]),
                )
                return Conversation.model_validate(conv_row), Task.model_validate(row), True
        except _KeyTaken:
            return await self.start(
                owner=owner,
                model=model,
                prompt=prompt,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
                project_id=project_id,
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
            conv = await self._lock(conn, owner, conversation_id)
            if idempotency_key is not None:
                existing = await task_by_key(conn, owner, idempotency_key)
                if existing is not None:
                    return _same_turn(existing, conversation_id, prompt), False
            cur = await conn.execute(_TREE, (conversation_id,))
            rows = await cur.fetchall()
            _busy(rows)
            path = path_to(rows, conv["head_id"])
            return await self._add_turn(
                conn,
                conv,
                owner=owner,
                prompt=prompt,
                model=model,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
                parent=path[-1]["id"] if path else None,
                context=context_of(path, context_turns),
                summary_of=left_out(path, context_turns),
                turn=len(path) + 1,
            ), True

    async def add_version(
        self,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        owner: str,
        prompt: str | None,
        model: str | None,
        max_attempts: int,
        idempotency_key: str | None,
        context_turns: int,
    ) -> tuple[Task, bool]:
        """Edit (`prompt` given) or regenerate (`prompt` None) a message: a new
        version of turn `turn_id`, with the same earlier turns, becomes the shown
        path's end. Raises ChatError not_found, turn_in_progress or
        idempotency_conflict."""
        async with self.pool.connection() as conn, conn.transaction():
            conv = await self._lock(conn, owner, conversation_id)
            cur = await conn.execute(_TREE, (conversation_id,))
            rows = await cur.fetchall()
            target = next((r for r in rows if r["id"] == turn_id), None)
            if target is None:
                raise ChatError("not_found", "No such message in this conversation.")
            text = target["prompt"] if prompt is None else prompt
            if idempotency_key is not None:
                existing = await task_by_key(conn, owner, idempotency_key)
                if existing is not None:
                    return _same_turn(existing, conversation_id, text), False
            _busy(rows)
            earlier = path_to(rows, target["parent_id"])
            return await self._add_turn(
                conn,
                conv,
                owner=owner,
                prompt=text,
                model=model,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
                parent=target["parent_id"],
                context=context_of(earlier, context_turns),
                summary_of=left_out(earlier, context_turns),
                turn=target["turn"],
            ), True

    async def show(self, conversation_id: uuid.UUID, turn_id: uuid.UUID, *, owner: str) -> None:
        """Show the version `turn_id`: the path now runs through it to its newest
        descendant. Raises ChatError not_found or turn_in_progress (switching away
        from a turn being answered would hide it)."""
        async with self.pool.connection() as conn, conn.transaction():
            await self._lock(conn, owner, conversation_id)
            cur = await conn.execute(_TREE, (conversation_id,))
            rows = await cur.fetchall()
            if not any(r["id"] == turn_id for r in rows):
                raise ChatError("not_found", "No such message in this conversation.")
            _busy(rows)
            await conn.execute(
                "UPDATE conversations SET head_id = %s WHERE id = %s",
                (newest_leaf(rows, turn_id), conversation_id),
            )

    async def _lock(
        self, conn: AsyncConnection[DictRow], owner: str, conversation_id: uuid.UUID
    ) -> DictRow:
        cur = await conn.execute(
            "SELECT * FROM conversations WHERE id = %s AND owner = %s FOR UPDATE",
            (conversation_id, owner),
        )
        conv = await cur.fetchone()
        if conv is None:
            raise ChatError("not_found", "No such conversation.")
        return conv

    async def _add_turn(
        self,
        conn: AsyncConnection[DictRow],
        conv: DictRow,
        *,
        owner: str,
        prompt: str,
        model: str | None,
        max_attempts: int,
        idempotency_key: str | None,
        parent: uuid.UUID | None,
        context: list[ContextMessage],
        summary_of: uuid.UUID | None,
        turn: int,
    ) -> Task:
        """Insert a turn under the conversation lock and make it the shown path's end."""
        use_model = model or conv["model"]
        row = await insert_task(
            conn,
            created_by=owner,
            title=conv["title"],
            model=use_model,
            prompt=prompt,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            conversation_id=conv["id"],
            turn=turn,
            parent_id=parent,
            context=context,
            summary_of=summary_of,
            **await project_context(conn, owner, conv["project_id"]),
        )
        if row is None:  # pragma: no cover - the key was checked under the lock
            raise RuntimeError("idempotency key taken under the conversation lock")
        await conn.execute(
            "UPDATE conversations SET model = %s, head_id = %s, updated_at = now() WHERE id = %s",
            (use_model, row["id"], conv["id"]),
        )
        return Task.model_validate(row)

    async def rename(self, conversation_id: uuid.UUID, *, owner: str, title: str) -> Conversation:
        """Retitle a conversation and its turns (the Tasks list shows turns by it).
        Not counted as activity: the list order stays. Raises ChatError not_found."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE conversations SET title = %s WHERE id = %s AND owner = %s RETURNING *",
                (title, conversation_id, owner),
            )
            row = await cur.fetchone()
            if row is None:
                raise ChatError("not_found", "No such conversation.")
            await conn.execute(
                "UPDATE tasks SET title = %s WHERE conversation_id = %s", (title, conversation_id)
            )
            return Conversation.model_validate(row)

    async def move(
        self, conversation_id: uuid.UUID, *, owner: str, project_id: uuid.UUID | None
    ) -> Conversation:
        """Put a conversation in a project, or take it out (None). Turns sent from
        now on get the new project's instructions. Not counted as activity. Raises
        ChatError not_found or project_not_found."""
        async with self.pool.connection() as conn, conn.transaction():
            await project_context(conn, owner, project_id)  # the project must be the owner's
            cur = await conn.execute(
                "UPDATE conversations SET project_id = %s WHERE id = %s AND owner = %s RETURNING *",
                (project_id, conversation_id, owner),
            )
            row = await cur.fetchone()
            if row is None:
                raise ChatError("not_found", "No such conversation.")
            return Conversation.model_validate(row)

    async def delete(self, conversation_id: uuid.UUID, *, owner: str) -> int:
        """Delete a conversation with its turns and their events; returns how many
        turns it had. Raises ChatError not_found or turn_in_progress."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT id FROM conversations WHERE id = %s AND owner = %s FOR UPDATE",
                (conversation_id, owner),
            )
            if await cur.fetchone() is None:
                raise ChatError("not_found", "No such conversation.")
            cur = await conn.execute(
                "SELECT state FROM tasks WHERE conversation_id = %s", (conversation_id,)
            )
            states = [r["state"] for r in await cur.fetchall()]
            if any(s in UNFINISHED for s in states):
                raise ChatError(
                    "turn_in_progress",
                    "A message is still being answered. Stop it before deleting the conversation.",
                )
            await conn.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            return len(states)

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

    async def turns(self, conversation_id: uuid.UUID) -> list[Turn]:
        """The shown path, first message first, each turn with its versions."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT head_id FROM conversations WHERE id = %s", (conversation_id,)
            )
            conv = await cur.fetchone()
            cur = await conn.execute(
                "SELECT * FROM tasks WHERE conversation_id = %s ORDER BY created_at, id",
                (conversation_id,),
            )
            rows = await cur.fetchall()
        siblings: dict[uuid.UUID | None, list[uuid.UUID]] = {}
        for r in rows:
            siblings.setdefault(r["parent_id"], []).append(r["id"])
        path = path_to(rows, conv["head_id"] if conv else None)
        return [Turn(task=Task.model_validate(r), versions=siblings[r["parent_id"]]) for r in path]

    async def list(
        self,
        owner: str,
        *,
        limit: int,
        query: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> list[ConversationSummary]:
        """Most recently active first. With `query`, only conversations whose title,
        or any message or answer, contains it (case-insensitive). With `project_id`,
        only that project's."""
        pattern = None if query is None else _like(query)
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT c.*, coalesce(h.turn, 0) AS turns, h.state AS last_state
                FROM conversations c LEFT JOIN tasks h ON h.id = c.head_id
                WHERE c.owner = %(owner)s
                  AND (%(project)s::uuid IS NULL OR c.project_id = %(project)s)
                  AND (%(pattern)s::text IS NULL
                       OR c.title ILIKE %(pattern)s
                       OR EXISTS (SELECT 1 FROM tasks m WHERE m.conversation_id = c.id
                                  AND (m.prompt ILIKE %(pattern)s
                                       OR m.result_text ILIKE %(pattern)s)))
                ORDER BY c.updated_at DESC, c.id
                LIMIT %(limit)s
                """,
                {"owner": owner, "pattern": pattern, "limit": limit, "project": project_id},
            )
            rows = await cur.fetchall()
        return [ConversationSummary.model_validate(r) for r in rows]
