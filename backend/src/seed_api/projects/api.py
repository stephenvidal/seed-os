"""Projects API: create, list, rename, set instructions, delete. Conversations join
a project when started in it or moved into it (chat/api.py)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator

from ..auth import AuthStoreDep, Principal, client_ip, require_role
from ..errors import ApiError
from .knowledge import MAX_DOCUMENT_CHARS, TEXT_SUFFIXES, Document, KnowledgeStore, NameTaken
from .memory import MAX_NOTE_CHARS, Memory, MemoryStore, Status
from .store import ProjectStore, ProjectSummary

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

AdminOnly = Annotated[Principal, Depends(require_role("admin"))]
MAX_INSTRUCTIONS = 20_000


def get_projects(request: Request) -> ProjectStore:
    store: ProjectStore | None = getattr(request.app.state, "project_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Projects need a database. Set SEED_DATABASE_URL."
        )
    return store


ProjectsDep = Annotated[ProjectStore, Depends(get_projects)]


def get_memory(request: Request) -> MemoryStore:
    store: MemoryStore | None = getattr(request.app.state, "memory_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Projects need a database. Set SEED_DATABASE_URL."
        )
    return store


MemoryDep = Annotated[MemoryStore, Depends(get_memory)]


def get_knowledge(request: Request) -> KnowledgeStore:
    store: KnowledgeStore | None = getattr(request.app.state, "knowledge_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Projects need a database. Set SEED_DATABASE_URL."
        )
    return store


KnowledgeDep = Annotated[KnowledgeStore, Depends(get_knowledge)]


def tidy_name(v: str) -> str:
    """Runs of whitespace become one space; the result must be 1-80 characters."""
    v = " ".join(v.split())
    if not v:
        raise ValueError("Name must not be blank.")
    if len(v) > 80:
        raise ValueError("Name must be at most 80 characters.")
    return v


class NewProject(BaseModel):
    name: str = Field(max_length=200)
    instructions: str = Field(default="", max_length=MAX_INSTRUCTIONS)

    _name = field_validator("name")(tidy_name)

    @field_validator("instructions")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class ProjectChange(BaseModel):
    # Left out: unchanged.
    name: str | None = Field(default=None, max_length=200)
    instructions: str | None = Field(default=None, max_length=MAX_INSTRUCTIONS)

    @field_validator("name")
    @classmethod
    def name_ok(cls, v: str | None) -> str | None:
        return None if v is None else tidy_name(v)

    @field_validator("instructions")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return None if v is None else v.strip()


async def _project(store: ProjectStore, owner: str, project_id: uuid.UUID) -> ProjectSummary:
    project = await store.get(owner, project_id)
    if project is None:
        raise ApiError(404, "not_found", "No such project.")
    return project


@router.get("", response_model=list[ProjectSummary])
async def list_projects(principal: AdminOnly, store: ProjectsDep) -> list[ProjectSummary]:
    """The signed-in user's projects, most recently changed first."""
    return await store.list(principal.username)


@router.post("", response_model=ProjectSummary, status_code=201)
async def create_project(
    body: NewProject,
    request: Request,
    principal: AdminOnly,
    store: ProjectsDep,
    audit: AuthStoreDep,
) -> ProjectSummary:
    project = await store.create(
        owner=principal.username, name=body.name, instructions=body.instructions
    )
    await audit.audit(
        "project_created",
        actor=principal.username,
        target=str(project.id),
        ip=client_ip(request),
        detail={"name": project.name},
    )
    return project


@router.get("/{project_id}", response_model=ProjectSummary)
async def get_project(
    project_id: uuid.UUID, principal: AdminOnly, store: ProjectsDep
) -> ProjectSummary:
    return await _project(store, principal.username, project_id)


@router.patch("/{project_id}", response_model=ProjectSummary)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectChange,
    request: Request,
    principal: AdminOnly,
    store: ProjectsDep,
    audit: AuthStoreDep,
) -> ProjectSummary:
    """Rename a project or change its instructions. New instructions reach the
    model from the next message sent in the project."""
    project = await store.update(
        project_id, owner=principal.username, name=body.name, instructions=body.instructions
    )
    if project is None:
        raise ApiError(404, "not_found", "No such project.")
    await audit.audit(
        "project_updated",
        actor=principal.username,
        target=str(project_id),
        ip=client_ip(request),
        detail={"fields": sorted(body.model_dump(exclude_none=True))},
    )
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    request: Request,
    principal: AdminOnly,
    store: ProjectsDep,
    audit: AuthStoreDep,
) -> Response:
    """Delete a project. Its conversations are kept and leave the project."""
    released = await store.delete(project_id, owner=principal.username)
    if released is None:
        raise ApiError(404, "not_found", "No such project.")
    await audit.audit(
        "project_deleted",
        actor=principal.username,
        target=str(project_id),
        ip=client_ip(request),
        detail={"conversations": released},
    )
    return Response(status_code=204)


def tidy_note(v: str) -> str:
    """Runs of whitespace become one space; the result must not be blank."""
    v = " ".join(v.split())
    if not v:
        raise ValueError("The note must not be blank.")
    return v


class NewNote(BaseModel):
    content: str = Field(max_length=MAX_NOTE_CHARS)

    _content = field_validator("content")(tidy_note)


class NoteChange(BaseModel):
    # Left out: unchanged.
    content: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    # True approves a proposed note (it then reaches the model).
    approve: bool = False

    @field_validator("content")
    @classmethod
    def content_ok(cls, v: str | None) -> str | None:
        return None if v is None else tidy_note(v)


@router.get("/{project_id}/memories", response_model=list[Memory])
async def list_memories(
    project_id: uuid.UUID,
    principal: AdminOnly,
    store: ProjectsDep,
    memory: MemoryDep,
    status: Status | None = None,
) -> list[Memory]:
    """The project's memory: proposals waiting for approval first, then approved
    notes, newest first. `status` keeps one kind."""
    await _project(store, principal.username, project_id)
    return await memory.list(principal.username, project_id, status=status)


@router.post("/{project_id}/memories", response_model=Memory, status_code=201)
async def add_memory(
    project_id: uuid.UUID,
    body: NewNote,
    request: Request,
    principal: AdminOnly,
    memory: MemoryDep,
    audit: AuthStoreDep,
) -> Memory:
    """Add a note; the owner's own notes are approved as written."""
    note = await memory.add(principal.username, project_id, body.content)
    if note is None:
        raise ApiError(404, "not_found", "No such project.")
    await audit.audit(
        "memory_added", actor=principal.username, target=str(note.id), ip=client_ip(request)
    )
    return note


@router.patch("/{project_id}/memories/{memory_id}", response_model=Memory)
async def update_memory(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    body: NoteChange,
    request: Request,
    principal: AdminOnly,
    memory: MemoryDep,
    audit: AuthStoreDep,
) -> Memory:
    """Edit a note, approve a proposal (`approve: true`), or both. Changes reach the
    model from the next message sent in the project."""
    note = await memory.update(
        principal.username, project_id, memory_id, content=body.content, approve=body.approve
    )
    if note is None:
        raise ApiError(404, "not_found", "No such note.")
    await audit.audit(
        "memory_approved" if body.approve else "memory_updated",
        actor=principal.username,
        target=str(memory_id),
        ip=client_ip(request),
        detail={"edited": body.content is not None},
    )
    return note


@router.delete("/{project_id}/memories/{memory_id}", status_code=204)
async def delete_memory(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    request: Request,
    principal: AdminOnly,
    memory: MemoryDep,
    audit: AuthStoreDep,
) -> Response:
    """Delete a note, or reject a proposal."""
    if not await memory.delete(principal.username, project_id, memory_id):
        raise ApiError(404, "not_found", "No such note.")
    await audit.audit(
        "memory_deleted", actor=principal.username, target=str(memory_id), ip=client_ip(request)
    )
    return Response(status_code=204)


class NewDocument(BaseModel):
    name: str = Field(max_length=200)
    # The file's text, read by the browser.
    content: str = Field(max_length=MAX_DOCUMENT_CHARS)

    @field_validator("name")
    @classmethod
    def name_ok(cls, v: str) -> str:
        v = v.strip()
        if not v or "/" in v or "\\" in v:
            raise ValueError("Give the file name only.")
        if not v.lower().endswith(TEXT_SUFFIXES):
            raise ValueError(f"Only text documents: {', '.join(TEXT_SUFFIXES)}.")
        return v

    @field_validator("content")
    @classmethod
    def content_ok(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("The document is empty.")
        if "\x00" in v:
            raise ValueError("The document is not text.")
        return v


@router.get("/{project_id}/documents", response_model=list[Document])
async def list_documents(
    project_id: uuid.UUID, principal: AdminOnly, store: ProjectsDep, knowledge: KnowledgeDep
) -> list[Document]:
    """The project's knowledge documents, by name."""
    await _project(store, principal.username, project_id)
    return await knowledge.documents(principal.username, project_id)


@router.post("/{project_id}/documents", response_model=Document, status_code=201)
async def add_document(
    project_id: uuid.UUID,
    body: NewDocument,
    request: Request,
    principal: AdminOnly,
    knowledge: KnowledgeDep,
    audit: AuthStoreDep,
) -> Document:
    """Add a text document; the agent can search it in the project's chats from the
    next message on. 409 name_taken when the project has one by that name."""
    try:
        doc = await knowledge.add(principal.username, project_id, body.name, body.content)
    except NameTaken:
        raise ApiError(
            409, "name_taken", "This project already has a document with that name."
        ) from None
    if doc is None:
        raise ApiError(404, "not_found", "No such project.")
    await audit.audit(
        "document_added",
        actor=principal.username,
        target=str(doc.id),
        ip=client_ip(request),
        detail={"name": doc.name, "chars": doc.chars},
    )
    return doc


@router.delete("/{project_id}/documents/{document_id}", status_code=204)
async def delete_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    principal: AdminOnly,
    knowledge: KnowledgeDep,
    audit: AuthStoreDep,
) -> Response:
    if not await knowledge.delete(principal.username, project_id, document_id):
        raise ApiError(404, "not_found", "No such document.")
    await audit.audit(
        "document_deleted", actor=principal.username, target=str(document_id), ip=client_ip(request)
    )
    return Response(status_code=204)
