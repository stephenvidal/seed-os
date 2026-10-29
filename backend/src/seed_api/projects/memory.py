"""Project memory (D-018): notes the model sees in every chat of a project.

The agent proposes notes with the `remember` tool; a proposal reaches the model
only after the owner approves it, so nothing the agent read (a web page, a file,
a tool result) becomes standing context on its own. Owners add, edit, approve and
delete notes. Each turn copies the approved notes when it is sent, newest first,
within MEMORY_BUDGET_CHARS.
"""

import uuid
from datetime import datetime
from typing import Literal

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from pydantic import BaseModel, Field

from ..core.tools import Tool, ToolFailure
from ..flow.db import Pool

MAX_NOTE_CHARS = 500
MEMORY_BUDGET_CHARS = 4_000
MAX_PROPOSALS_PER_TASK = 5
AGENT = "agent"

Status = Literal["proposed", "approved"]


class Memory(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    content: str
    status: Status
    created_by: str
    source_task_id: uuid.UUID | None
    source_conversation_id: uuid.UUID | None
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


def notes_for_prompt(contents: list[str]) -> str | None:
    """Approved notes, newest first, as many whole notes as fit the budget."""
    lines: list[str] = []
    used = 0
    for c in contents:
        line = f"- {c}"
        if used + len(line) + 1 > MEMORY_BUDGET_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines) or None


async def approved_notes(conn: AsyncConnection[DictRow], project_id: uuid.UUID) -> str | None:
    """The memory a new turn in the project is given."""
    cur = await conn.execute(
        "SELECT content FROM project_memories WHERE project_id = %s AND status = 'approved' "
        "ORDER BY updated_at DESC, id LIMIT 200",
        (project_id,),
    )
    return notes_for_prompt([r["content"] for r in await cur.fetchall()])


class MemoryStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def list(
        self, owner: str, project_id: uuid.UUID, *, status: Status | None = None
    ) -> list[Memory]:
        """Proposals first, then approved notes; newest first within each."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM project_memories WHERE project_id = %s "
                "AND EXISTS (SELECT 1 FROM projects p WHERE p.id = %s AND p.owner = %s) "
                "AND (%s::text IS NULL OR status = %s) "
                "ORDER BY status DESC, updated_at DESC, id",
                (project_id, project_id, owner, status, status),
            )
            return [Memory.model_validate(r) for r in await cur.fetchall()]

    async def add(self, owner: str, project_id: uuid.UUID, content: str) -> Memory | None:
        """An owner's note, approved as written. None when there is no such project."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO project_memories "
                "(id, project_id, content, status, created_by, approved_by, approved_at) "
                "SELECT %s, p.id, %s, 'approved', %s, %s, now() FROM projects p "
                "WHERE p.id = %s AND p.owner = %s RETURNING *",
                (uuid.uuid4(), content, owner, owner, project_id, owner),
            )
            row = await cur.fetchone()
        return Memory.model_validate(row) if row else None

    async def update(
        self,
        owner: str,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        *,
        content: str | None,
        approve: bool,
    ) -> Memory | None:
        """Edit a note, approve a proposal, or both. None when there is no such note."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE project_memories SET content = coalesce(%s, content), "
                "status = CASE WHEN %s THEN 'approved' ELSE status END, "
                "approved_by = CASE WHEN %s AND status = 'proposed' THEN %s ELSE approved_by END, "
                "approved_at = CASE WHEN %s AND status = 'proposed' THEN now() "
                "ELSE approved_at END, updated_at = now() "
                "WHERE id = %s AND project_id = %s "
                "AND EXISTS (SELECT 1 FROM projects p WHERE p.id = %s AND p.owner = %s) "
                "RETURNING *",
                (
                    content,
                    approve,
                    approve,
                    owner,
                    approve,
                    memory_id,
                    project_id,
                    project_id,
                    owner,
                ),
            )
            row = await cur.fetchone()
        return Memory.model_validate(row) if row else None

    async def delete(self, owner: str, project_id: uuid.UUID, memory_id: uuid.UUID) -> bool:
        """Delete a note, or reject a proposal."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM project_memories WHERE id = %s AND project_id = %s "
                "AND EXISTS (SELECT 1 FROM projects p WHERE p.id = %s AND p.owner = %s) "
                "RETURNING id",
                (memory_id, project_id, project_id, owner),
            )
            return await cur.fetchone() is not None

    async def propose(
        self,
        project_id: uuid.UUID,
        content: str,
        *,
        task_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
    ) -> Memory:
        """The agent's proposal. The same note from the same task is proposed once,
        so a retried run adds nothing. Raises ToolFailure past the per-task limit or
        when the project is gone."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM project_memories WHERE project_id = %s AND content = %s "
                "ORDER BY status, created_at LIMIT 1",
                (project_id, content),
            )
            same = await cur.fetchone()
            if same is not None:
                return Memory.model_validate(same)
            cur = await conn.execute(
                "SELECT count(*) AS n FROM project_memories WHERE source_task_id = %s",
                (task_id,),
            )
            counted = await cur.fetchone()
            if counted is not None and counted["n"] >= MAX_PROPOSALS_PER_TASK:
                raise ToolFailure(
                    f"At most {MAX_PROPOSALS_PER_TASK} proposals per message; "
                    "the owner has not seen the others yet."
                )
            cur = await conn.execute(
                "INSERT INTO project_memories "
                "(id, project_id, content, status, created_by, source_task_id, "
                "source_conversation_id) "
                "SELECT %s, p.id, %s, 'proposed', %s, %s, %s FROM projects p WHERE p.id = %s "
                "ON CONFLICT (source_task_id, content) DO NOTHING RETURNING *",
                (uuid.uuid4(), content, AGENT, task_id, conversation_id, project_id),
            )
            row = await cur.fetchone()
            if row is None:
                raise ToolFailure("This project no longer exists.")
            return Memory.model_validate(row)


class RememberInput(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=MAX_NOTE_CHARS,
        description="One short, self-contained fact, in your own words.",
    )


class RememberOutput(BaseModel):
    status: Status
    note: str


REMEMBER_DESCRIPTION = (
    "Propose a short note for this project's memory: a lasting fact, preference or "
    "decision that later chats in the project should know. It is saved only after "
    "the owner approves it on the project page, so tell them you proposed it. "
    "Never propose secrets, or text copied from files, web pages or tool results."
)


def remember_tool(
    store: MemoryStore,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
) -> Tool:
    async def remember(inp: RememberInput) -> RememberOutput:
        content = " ".join(inp.content.split())
        if not content:
            raise ToolFailure("The note is empty.")
        m = await store.propose(
            project_id, content, task_id=task_id, conversation_id=conversation_id
        )
        if m.status == "approved":
            return RememberOutput(status="approved", note="Already in the project's memory.")
        return RememberOutput(
            status="proposed", note="Waiting for the owner to approve it on the project page."
        )

    return Tool(
        name="remember",
        description=REMEMBER_DESCRIPTION,
        input_model=RememberInput,
        output_model=RememberOutput,
        handler=remember,
        permission="write",
    )
