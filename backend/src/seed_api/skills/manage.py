"""`skill_manage` (D-033): the agent saves what it learned as a skill, or changes or
deletes one, and every call waits for the owner's approval. SEED writes the
owner's shared skills; an agent writes only its own private ones."""

import uuid
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from ..core.tools import Tool, ToolFailure
from .rules import clean_body, clean_description, clean_name, clean_tags
from .store import NameTaken, NoSuchAgent, SkillStore


class SkillManageInput(BaseModel):
    action: Literal["create", "update", "delete"]
    name: str = Field(max_length=64, description="The skill's name: lower case, digits, hyphens.")
    description: str | None = Field(
        default=None, max_length=1024, description="What it is for. Needed to create."
    )
    tags: list[str] | None = Field(default=None, max_length=20)
    instructions: str | None = Field(
        default=None,
        max_length=20_000,
        description=(
            "The procedure: when to use it, the steps, pitfalls, how to check the result. "
            "Needed to create. Write lessons, not a log of this task."
        ),
    )

    @field_validator("name")
    @classmethod
    def name_ok(cls, v: str) -> str:
        return clean_name(v)

    @field_validator("description")
    @classmethod
    def description_ok(cls, v: str | None) -> str | None:
        return None if v is None else clean_description(v)

    @field_validator("tags")
    @classmethod
    def tags_ok(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else clean_tags(v)

    @field_validator("instructions")
    @classmethod
    def instructions_ok(cls, v: str | None) -> str | None:
        return None if v is None else clean_body(v)

    @model_validator(mode="after")
    def complete(self) -> Self:
        given = [self.description, self.tags, self.instructions]
        if self.action == "create" and (self.description is None or self.instructions is None):
            raise ValueError("Creating a skill needs a description and instructions.")
        if self.action == "update" and all(v is None for v in given):
            raise ValueError("Say what to change: description, tags or instructions.")
        return self


class SkillManageOutput(BaseModel):
    action: str
    name: str
    done: bool


def skill_manage_tool(
    store: SkillStore, *, owner: str, agent_id: uuid.UUID | None, task_id: uuid.UUID
) -> Tool:
    """For a task of `owner`'s; `agent_id` set when it is that agent's task."""

    async def mine(name: str) -> uuid.UUID:
        skill = await store.named(owner, name)
        if skill is None or skill.agent_id != agent_id:
            raise ToolFailure(f"You have no skill called {name} that you may change.")
        return skill.id

    async def manage(inp: SkillManageInput) -> SkillManageOutput:
        try:
            if inp.action == "create":
                assert inp.description is not None and inp.instructions is not None  # noqa: S101
                await store.create(
                    owner=owner,
                    agent_id=agent_id,
                    name=inp.name,
                    description=inp.description,
                    tags=inp.tags or [],
                    body=inp.instructions,
                    written_by_task=task_id,
                )
            elif inp.action == "update":
                skill_id = await mine(inp.name)
                old = await store.get(owner, skill_id)
                if old is None:
                    raise ToolFailure(f"The skill {inp.name} was deleted meanwhile.")
                await store.update(
                    skill_id,
                    owner=owner,
                    agent_id=agent_id,
                    name=old.name,
                    description=inp.description or old.description,
                    tags=old.tags if inp.tags is None else inp.tags,
                    body=inp.instructions or old.body,
                    written_by_task=task_id,
                )
            elif not await store.delete(owner, await mine(inp.name)):
                raise ToolFailure(f"The skill {inp.name} was deleted meanwhile.")
        except NameTaken:
            raise ToolFailure(
                f"A skill called {inp.name} exists already; update it or choose another name."
            ) from None
        except NoSuchAgent:
            raise ToolFailure("The agent this task runs as was deleted.") from None
        return SkillManageOutput(action=inp.action, name=inp.name, done=True)

    return Tool(
        name="skill_manage",
        description=(
            "Save a procedure worth repeating as a skill, or change or delete one of "
            "yours: after a multi-step job that worked, a dead end you found a way "
            "around, or a correction from the owner. The owner approves each call "
            "first. "
            + (
                "Your skills are private to you."
                if agent_id is not None
                else "Skills you save are the owner's shared skills."
            )
        ),
        input_model=SkillManageInput,
        output_model=SkillManageOutput,
        handler=manage,
        permission="write",
        requires_approval=True,
    )
