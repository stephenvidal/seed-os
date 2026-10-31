"""Skills API (D-033): write, import, list, change and delete the owner's skills."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..auth import AuthStore, AuthStoreDep, Principal, client_ip, require_role
from ..errors import ApiError
from .rules import clean_body, clean_description, clean_name, clean_tags
from .skillmd import MAX_TEXT, SkillMdError, parse
from .store import NameTaken, NoSuchAgent, Skill, SkillStore

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

AdminOnly = Annotated[Principal, Depends(require_role("admin"))]


def get_skills(request: Request) -> SkillStore:
    store: SkillStore | None = getattr(request.app.state, "skill_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Skills need a database. Set SEED_DATABASE_URL."
        )
    return store


SkillsDep = Annotated[SkillStore, Depends(get_skills)]


class SkillIn(BaseModel):
    """A whole skill: creating and changing one both send all of it."""

    name: str = Field(max_length=200)
    description: str = Field(max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    body: str = Field(max_length=MAX_TEXT)
    # Private to this agent of the owner's; None: shared.
    agent_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def name_ok(cls, v: str) -> str:
        return clean_name(v)

    @field_validator("description")
    @classmethod
    def description_ok(cls, v: str) -> str:
        return clean_description(v)

    @field_validator("tags")
    @classmethod
    def tags_ok(cls, v: list[str]) -> list[str]:
        return clean_tags(v)

    @field_validator("body")
    @classmethod
    def body_ok(cls, v: str) -> str:
        return clean_body(v)


class ImportIn(BaseModel):
    text: str = Field(max_length=MAX_TEXT + 1)
    agent_id: uuid.UUID | None = None


class Imported(BaseModel):
    skill: Skill
    # Header keys SEED does not act on, so the person knows what was left out.
    ignored: list[str]


def _taken(name: str) -> ApiError:
    return ApiError(409, "name_taken", f"You already have a skill called {name}.")


def _no_agent() -> ApiError:
    return ApiError(422, "no_such_agent", "That agent does not exist.")


def _from_skill_md(text: str, agent_id: uuid.UUID | None) -> tuple[SkillIn, list[str]]:
    """A skill from a SKILL.md's text, and the header keys SEED ignores; or 422."""
    try:
        md = parse(text)
        skill_in = SkillIn.model_validate(
            {
                "name": md.name,
                "description": md.description,
                "tags": md.tags,
                "body": md.body,
                "agent_id": agent_id,
            }
        )
    except SkillMdError as e:
        raise ApiError(422, "invalid_skill_md", str(e)) from None
    except ValidationError as e:
        first = e.errors()[0]
        field = ".".join(str(p) for p in first["loc"]) or "header"
        message = str(first.get("ctx", {}).get("error", first["msg"]))
        raise ApiError(422, "invalid_skill_md", f"{field}: {message}") from None
    return skill_in, md.ignored


@router.get("", response_model=list[Skill])
async def list_skills(principal: AdminOnly, store: SkillsDep) -> list[Skill]:
    """The signed-in user's skills, shared and private, by name."""
    return await store.all(principal.username)


async def _create(
    body: SkillIn, request: Request, principal: Principal, store: SkillStore, audit: AuthStore
) -> Skill:
    try:
        skill = await store.create(owner=principal.username, **body.model_dump())
    except NameTaken:
        raise _taken(body.name) from None
    except NoSuchAgent:
        raise _no_agent() from None
    await audit.audit(
        "skill_created",
        actor=principal.username,
        target=str(skill.id),
        ip=client_ip(request),
        detail={"name": skill.name, "agent_id": str(skill.agent_id) if skill.agent_id else None},
    )
    return skill


@router.post("", response_model=Skill, status_code=201)
async def create_skill(
    body: SkillIn, request: Request, principal: AdminOnly, store: SkillsDep, audit: AuthStoreDep
) -> Skill:
    return await _create(body, request, principal, store, audit)


@router.post("/import", response_model=Imported, status_code=201)
async def import_skill(
    body: ImportIn, request: Request, principal: AdminOnly, store: SkillsDep, audit: AuthStoreDep
) -> Imported:
    """Add a skill from the text of a Hermes Agent SKILL.md."""
    skill_in, ignored = _from_skill_md(body.text, body.agent_id)
    return Imported(
        skill=await _create(skill_in, request, principal, store, audit), ignored=ignored
    )


# A Hermes Agent skills folder (~/.hermes/skills/), as the browser reads it: every
# SKILL.md in it, by its path in the folder (D-043).
MAX_FOLDER_FILES = 300
MAX_FOLDER_CHARS = 3_000_000


class FolderFile(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    text: str = Field(max_length=MAX_TEXT + 1)


class FolderIn(BaseModel):
    files: list[FolderFile] = Field(min_length=1, max_length=MAX_FOLDER_FILES)
    agent_id: uuid.UUID | None = None

    @field_validator("files")
    @classmethod
    def size_ok(cls, v: list[FolderFile]) -> list[FolderFile]:
        if sum(len(f.text) for f in v) > MAX_FOLDER_CHARS:
            raise ValueError(f"At most {MAX_FOLDER_CHARS} characters in all.")
        return v


FolderOutcome = Literal["new", "imported", "name_taken", "invalid"]


class FolderItem(BaseModel):
    path: str
    name: str | None
    description: str | None
    # new: would be imported (preview); name_taken: you have a skill by that name,
    # or an earlier file in the folder does; invalid: see `error`.
    outcome: FolderOutcome
    error: str | None = None


@router.post("/import-folder", response_model=list[FolderItem])
async def import_folder(
    body: FolderIn,
    request: Request,
    principal: AdminOnly,
    store: SkillsDep,
    audit: AuthStoreDep,
    preview: bool = False,
) -> list[FolderItem]:
    """Add every SKILL.md of a Hermes Agent skills folder, each as the single import
    would. One that cannot be read, or whose name is taken, is listed and skipped;
    the rest are imported. `preview=true` saves nothing."""
    taken = {s.name for s in await store.all(principal.username)}
    out: list[FolderItem] = []
    for f in body.files:
        try:
            skill_in, _ = _from_skill_md(f.text, body.agent_id)
        except ApiError as e:
            out.append(
                FolderItem(
                    path=f.path, name=None, description=None, outcome="invalid", error=e.message
                )
            )
            continue
        item = FolderItem(
            path=f.path, name=skill_in.name, description=skill_in.description, outcome="new"
        )
        if skill_in.name in taken:
            item.outcome = "name_taken"
        elif not preview:
            try:
                await _create(skill_in, request, principal, store, audit)
                item.outcome = "imported"
            except ApiError as e:
                if e.code != "name_taken":
                    raise
                item.outcome = "name_taken"
        taken.add(skill_in.name)
        out.append(item)
    return out


@router.get("/{skill_id}", response_model=Skill)
async def get_skill(skill_id: uuid.UUID, principal: AdminOnly, store: SkillsDep) -> Skill:
    skill = await store.get(principal.username, skill_id)
    if skill is None:
        raise ApiError(404, "not_found", "No such skill.")
    return skill


@router.put("/{skill_id}", response_model=Skill)
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillIn,
    request: Request,
    principal: AdminOnly,
    store: SkillsDep,
    audit: AuthStoreDep,
) -> Skill:
    try:
        skill = await store.update(skill_id, owner=principal.username, **body.model_dump())
    except NameTaken:
        raise _taken(body.name) from None
    except NoSuchAgent:
        raise _no_agent() from None
    if skill is None:
        raise ApiError(404, "not_found", "No such skill.")
    await audit.audit(
        "skill_updated",
        actor=principal.username,
        target=str(skill_id),
        ip=client_ip(request),
        detail={"name": skill.name, "agent_id": str(skill.agent_id) if skill.agent_id else None},
    )
    return skill


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: uuid.UUID,
    request: Request,
    principal: AdminOnly,
    store: SkillsDep,
    audit: AuthStoreDep,
) -> Response:
    if not await store.delete(principal.username, skill_id):
        raise ApiError(404, "not_found", "No such skill.")
    await audit.audit(
        "skill_deleted", actor=principal.username, target=str(skill_id), ip=client_ip(request)
    )
    return Response(status_code=204)
