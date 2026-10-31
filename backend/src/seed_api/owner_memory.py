"""Memory about the owner (D-040): notes SEED is given in every one of its own runs,
in any chat or project, like Hermes Agent's user profile.

SEED proposes a note with the `remember_owner` tool; it reaches the model only once
the owner approves it (Stephen's choice, 2026-10-31, as for project memory, D-018),
so nothing SEED read becomes standing context on its own. The owner adds, edits,
approves and deletes notes at /api/v1/memory. A run is given the approved notes as
they are when it starts, newest first, within MEMORY_BUDGET_CHARS.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator

from .auth import AuthStoreDep, Principal, client_ip, require_role
from .core.tools import Tool, ToolFailure
from .errors import ApiError
from .flow.db import Pool
from .projects.memory import MAX_NOTE_CHARS, MAX_PROPOSALS_PER_TASK, notes_for_prompt

AGENT = "agent"

Status = Literal["proposed", "approved"]


class OwnerMemory(BaseModel):
    id: uuid.UUID
    owner: str
    content: str
    status: Status
    created_by: str
    source_task_id: uuid.UUID | None
    source_conversation_id: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OwnerMemoryStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def for_prompt(self, owner: str) -> str | None:
        """The approved notes a run of the owner's is given."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT content FROM owner_memories WHERE owner = %s AND status = 'approved' "
                "ORDER BY updated_at DESC, id LIMIT 200",
                (owner,),
            )
            return notes_for_prompt([r["content"] for r in await cur.fetchall()])

    async def list(self, owner: str, *, status: Status | None = None) -> list[OwnerMemory]:
        """Proposals first, then approved notes; newest first within each."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM owner_memories WHERE owner = %s "
                "AND (%s::text IS NULL OR status = %s) "
                "ORDER BY status DESC, updated_at DESC, id",
                (owner, status, status),
            )
            return [OwnerMemory.model_validate(r) for r in await cur.fetchall()]

    async def add(self, owner: str, content: str) -> OwnerMemory:
        """An owner's own note, approved as written."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO owner_memories (id, owner, content, status, created_by, approved_at) "
                "VALUES (%s, %s, %s, 'approved', %s, now()) RETURNING *",
                (uuid.uuid4(), owner, content, owner),
            )
            row = await cur.fetchone()
        return OwnerMemory.model_validate(row)

    async def update(
        self, owner: str, memory_id: uuid.UUID, *, content: str | None, approve: bool
    ) -> OwnerMemory | None:
        """Edit a note, approve a proposal, or both. None when there is no such note."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE owner_memories SET content = coalesce(%s, content), "
                "status = CASE WHEN %s THEN 'approved' ELSE status END, "
                "approved_at = CASE WHEN %s AND status = 'proposed' THEN now() "
                "ELSE approved_at END, updated_at = now() "
                "WHERE id = %s AND owner = %s RETURNING *",
                (content, approve, approve, memory_id, owner),
            )
            row = await cur.fetchone()
        return OwnerMemory.model_validate(row) if row else None

    async def delete(self, owner: str, memory_id: uuid.UUID) -> bool:
        """Delete a note, or reject a proposal."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM owner_memories WHERE id = %s AND owner = %s RETURNING id",
                (memory_id, owner),
            )
            return await cur.fetchone() is not None

    async def propose(
        self,
        owner: str,
        content: str,
        *,
        task_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
    ) -> OwnerMemory:
        """SEED's proposal. A note the owner already has, or the same note from the
        same task, is not added again. Raises ToolFailure past the per-task limit."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM owner_memories WHERE owner = %s AND content = %s "
                "ORDER BY status, created_at LIMIT 1",
                (owner, content),
            )
            same = await cur.fetchone()
            if same is not None:
                return OwnerMemory.model_validate(same)
            cur = await conn.execute(
                "SELECT count(*) AS n FROM owner_memories WHERE source_task_id = %s", (task_id,)
            )
            counted = await cur.fetchone()
            if counted is not None and counted["n"] >= MAX_PROPOSALS_PER_TASK:
                raise ToolFailure(
                    f"At most {MAX_PROPOSALS_PER_TASK} proposals per message; "
                    "the owner has not seen the others yet."
                )
            cur = await conn.execute(
                "INSERT INTO owner_memories (id, owner, content, status, created_by, "
                "source_task_id, source_conversation_id) "
                "VALUES (%s, %s, %s, 'proposed', %s, %s, %s) "
                "ON CONFLICT (source_task_id, content) DO NOTHING RETURNING *",
                (uuid.uuid4(), owner, content, AGENT, task_id, conversation_id),
            )
            row = await cur.fetchone()
            if row is None:  # pragma: no cover - the SELECT above found no such note
                raise ToolFailure("The note could not be saved.")
            return OwnerMemory.model_validate(row)


class RememberInput(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=MAX_NOTE_CHARS,
        description="One short, self-contained fact about the owner, in your own words.",
    )


class RememberOutput(BaseModel):
    status: Status
    note: str


REMEMBER_DESCRIPTION = (
    "Propose a short note about the owner for your lasting memory: who they are, how they "
    "like to work, a preference or a standing decision that would help in any later chat. "
    "It is used only after the owner approves it on the Settings page, so tell them you "
    "proposed it. Never propose secrets, or text copied from files, web pages or tool results."
)


def remember_owner_tool(
    store: OwnerMemoryStore, *, owner: str, task_id: uuid.UUID, conversation_id: uuid.UUID | None
) -> Tool:
    async def remember_owner(inp: RememberInput) -> RememberOutput:
        content = " ".join(inp.content.split())
        if not content:
            raise ToolFailure("The note is empty.")
        m = await store.propose(owner, content, task_id=task_id, conversation_id=conversation_id)
        if m.status == "approved":
            return RememberOutput(status="approved", note="Already in your memory of the owner.")
        return RememberOutput(
            status="proposed", note="Waiting for the owner to approve it on the Settings page."
        )

    return Tool(
        name="remember_owner",
        description=REMEMBER_DESCRIPTION,
        input_model=RememberInput,
        output_model=RememberOutput,
        handler=remember_owner,
        permission="write",
    )


router = APIRouter(prefix="/api/v1/memory", tags=["memory"])
AdminOnly = Annotated[Principal, Depends(require_role("admin"))]


def get_store(request: Request) -> OwnerMemoryStore:
    store: OwnerMemoryStore | None = getattr(request.app.state, "owner_memory_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Memory needs a database. Set SEED_DATABASE_URL."
        )
    return store


StoreDep = Annotated[OwnerMemoryStore, Depends(get_store)]


def _tidy(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("The note must not be blank.")
    return v


class NewNote(BaseModel):
    content: str = Field(max_length=MAX_NOTE_CHARS)

    _content = field_validator("content")(_tidy)


class NoteChange(BaseModel):
    # Left out: unchanged.
    content: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    # True approves a proposed note (it then reaches the model).
    approve: bool = False

    @field_validator("content")
    @classmethod
    def content_ok(cls, v: str | None) -> str | None:
        return None if v is None else _tidy(v)


@router.get("", response_model=list[OwnerMemory])
async def list_notes(
    principal: AdminOnly, store: StoreDep, status: Status | None = None
) -> list[OwnerMemory]:
    """What SEED remembers about you: proposals waiting for approval first, then
    approved notes, newest first. `status` keeps one kind."""
    return await store.list(principal.username, status=status)


@router.post("", response_model=OwnerMemory, status_code=201)
async def add_note(
    body: NewNote, request: Request, principal: AdminOnly, store: StoreDep, audit: AuthStoreDep
) -> OwnerMemory:
    """Add a note; your own notes are approved as written."""
    note = await store.add(principal.username, body.content)
    await audit.audit(
        "owner_memory_added", actor=principal.username, target=str(note.id), ip=client_ip(request)
    )
    return note


@router.patch("/{memory_id}", response_model=OwnerMemory)
async def update_note(
    memory_id: uuid.UUID,
    body: NoteChange,
    request: Request,
    principal: AdminOnly,
    store: StoreDep,
    audit: AuthStoreDep,
) -> OwnerMemory:
    """Edit a note, approve a proposal (`approve: true`), or both. Changes reach the
    model from the next run that starts."""
    note = await store.update(
        principal.username, memory_id, content=body.content, approve=body.approve
    )
    if note is None:
        raise ApiError(404, "not_found", "No such note.")
    await audit.audit(
        "owner_memory_approved" if body.approve else "owner_memory_updated",
        actor=principal.username,
        target=str(memory_id),
        ip=client_ip(request),
        detail={"edited": body.content is not None},
    )
    return note


@router.delete("/{memory_id}", status_code=204)
async def delete_note(
    memory_id: uuid.UUID,
    request: Request,
    principal: AdminOnly,
    store: StoreDep,
    audit: AuthStoreDep,
) -> Response:
    """Delete a note, or reject a proposal."""
    if not await store.delete(principal.username, memory_id):
        raise ApiError(404, "not_found", "No such note.")
    await audit.audit(
        "owner_memory_deleted",
        actor=principal.username,
        target=str(memory_id),
        ip=client_ip(request),
    )
    return Response(status_code=204)
