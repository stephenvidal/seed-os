"""Agents API: define, list, change and delete the specialists the assistant can
delegate to (D-024)."""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator

from ..auth import AuthStoreDep, Principal, client_ip, require_role
from ..errors import ApiError
from .store import Agent, AgentStore, NameTaken, NoSuchSkill, ToolName

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

AdminOnly = Annotated[Principal, Depends(require_role("admin"))]
MAX_INSTRUCTIONS = 20_000
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,39}$")


def get_agents(request: Request) -> AgentStore:
    store: AgentStore | None = getattr(request.app.state, "agent_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Agents need a database. Set SEED_DATABASE_URL."
        )
    return store


AgentsDep = Annotated[AgentStore, Depends(get_agents)]


class AgentIn(BaseModel):
    """A whole definition: creating and changing an agent both send all of it."""

    name: str = Field(max_length=200)
    description: str = Field(max_length=2000)
    instructions: str = Field(default="", max_length=MAX_INSTRUCTIONS)
    # None or blank: the delegating task's model.
    model: str | None = Field(default=None, max_length=200)
    tools: list[ToolName] = Field(default_factory=list)
    # The owner's shared skills it may use (D-033). Left out: none for a new agent,
    # and a changed one keeps its list.
    skills: list[uuid.UUID] | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def name_ok(cls, v: str) -> str:
        v = " ".join(v.split())
        if not _NAME.match(v):
            raise ValueError(
                "Use 1-40 letters, digits, spaces, hyphens or underscores, "
                "starting with a letter or digit."
            )
        return v

    @field_validator("description")
    @classmethod
    def description_ok(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Say what the agent is for.")
        if len(v) > 500:
            raise ValueError("Keep the description to 500 characters.")
        return v

    @field_validator("instructions")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("model")
    @classmethod
    def model_ok(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


def _taken(name: str) -> ApiError:
    return ApiError(409, "name_taken", f"You already have an agent called {name}.")


def _no_skill() -> ApiError:
    return ApiError(422, "no_such_skill", "Allow only your own shared skills.")


@router.get("", response_model=list[Agent])
async def list_agents(principal: AdminOnly, store: AgentsDep) -> list[Agent]:
    """The signed-in user's agents, by name."""
    return await store.all(principal.username)


@router.post("", response_model=Agent, status_code=201)
async def create_agent(
    body: AgentIn, request: Request, principal: AdminOnly, store: AgentsDep, audit: AuthStoreDep
) -> Agent:
    try:
        agent = await store.create(owner=principal.username, **body.model_dump())
    except NameTaken:
        raise _taken(body.name) from None
    except NoSuchSkill:
        raise _no_skill() from None
    await audit.audit(
        "agent_created",
        actor=principal.username,
        target=str(agent.id),
        ip=client_ip(request),
        detail={"name": agent.name, "tools": list(agent.tools)},
    )
    return agent


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(agent_id: uuid.UUID, principal: AdminOnly, store: AgentsDep) -> Agent:
    agent = await store.get(principal.username, agent_id)
    if agent is None:
        raise ApiError(404, "not_found", "No such agent.")
    return agent


@router.put("/{agent_id}", response_model=Agent)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentIn,
    request: Request,
    principal: AdminOnly,
    store: AgentsDep,
    audit: AuthStoreDep,
) -> Agent:
    """Replace an agent's definition. Delegations already running keep the one
    they started with."""
    try:
        agent = await store.update(agent_id, owner=principal.username, **body.model_dump())
    except NameTaken:
        raise _taken(body.name) from None
    except NoSuchSkill:
        raise _no_skill() from None
    if agent is None:
        raise ApiError(404, "not_found", "No such agent.")
    await audit.audit(
        "agent_updated",
        actor=principal.username,
        target=str(agent_id),
        ip=client_ip(request),
        detail={"name": agent.name, "tools": list(agent.tools)},
    )
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    request: Request,
    principal: AdminOnly,
    store: AgentsDep,
    audit: AuthStoreDep,
) -> Response:
    if not await store.delete(principal.username, agent_id):
        raise ApiError(404, "not_found", "No such agent.")
    await audit.audit(
        "agent_deleted", actor=principal.username, target=str(agent_id), ip=client_ip(request)
    )
    return Response(status_code=204)
