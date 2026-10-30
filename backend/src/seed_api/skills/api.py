"""Skills API (D-033): write, import, list, change and delete the owner's skills."""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..auth import AuthStore, AuthStoreDep, Principal, client_ip, require_role
from ..errors import ApiError
from .skillmd import MAX_TEXT, SkillMdError, parse
from .store import NameTaken, NoSuchAgent, Skill, SkillStore

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

AdminOnly = Annotated[Principal, Depends(require_role("admin"))]
MAX_BODY = 20_000
MAX_TAGS = 20
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


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
        v = v.strip().lower()
        if not _NAME.match(v):
            raise ValueError(
                "Use 1-64 lower-case letters, digits or hyphens, starting with a letter or digit."
            )
        return v

    @field_validator("description")
    @classmethod
    def description_ok(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Say what the skill is for.")
        if len(v) > 1024:
            raise ValueError("Keep the description to 1024 characters.")
        return v

    @field_validator("tags")
    @classmethod
    def tags_ok(cls, v: list[str]) -> list[str]:
        tags = list(dict.fromkeys(t for t in (" ".join(x.split()) for x in v) if t))
        if len(tags) > MAX_TAGS:
            raise ValueError(f"Use at most {MAX_TAGS} tags.")
        if any(len(t) > 40 for t in tags):
            raise ValueError("Keep each tag to 40 characters.")
        return tags

    @field_validator("body")
    @classmethod
    def body_ok(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Write the skill's instructions.")
        if len(v) > MAX_BODY:
            raise ValueError(f"Keep the instructions to {MAX_BODY} characters.")
        return v


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
    try:
        md = parse(body.text)
        skill_in = SkillIn.model_validate(
            {
                "name": md.name,
                "description": md.description,
                "tags": md.tags,
                "body": md.body,
                "agent_id": body.agent_id,
            }
        )
    except SkillMdError as e:
        raise ApiError(422, "invalid_skill_md", str(e)) from None
    except ValidationError as e:
        first = e.errors()[0]
        field = ".".join(str(p) for p in first["loc"]) or "header"
        message = str(first.get("ctx", {}).get("error", first["msg"]))
        raise ApiError(422, "invalid_skill_md", f"{field}: {message}") from None
    return Imported(
        skill=await _create(skill_in, request, principal, store, audit), ignored=md.ignored
    )


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
