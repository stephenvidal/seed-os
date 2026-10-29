"""Projects API: create, list, rename, set instructions, delete. Conversations join
a project when started in it or moved into it (chat/api.py)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator

from ..auth import AuthStoreDep, Principal, client_ip, require_role
from ..errors import ApiError
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
