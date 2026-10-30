"""Skills in a task (D-033): the index its prompt carries, the `skill_list` and
`skill_view` tools that read a skill in full, and the `/name` prefix that makes a
turn follow one skill. A task gets the skills it may see when it starts; the
tools read from that copy, so a skill changed mid-run does not change the run."""

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from ..core.tools import Tool, ToolFailure
from .store import Skill

INDEX_LIMIT = 100
_PREFIX = re.compile(r"^/([A-Za-z0-9][A-Za-z0-9-]{0,63})(?:\s+(.*))?$", re.DOTALL)


def skills_index(skills: list[Skill]) -> str:
    """The prompt's list of skills: names and what each is for, never the bodies."""
    shown = skills[:INDEX_LIMIT]
    lines = "\n".join(f"- {s.name}: {s.description}" for s in shown)
    more = (
        f"\n({len(skills) - len(shown)} more: use skill_list to see them all.)"
        if len(skills) > len(shown)
        else ""
    )
    return (
        "Skills: procedures the owner saved for you. When a request matches one, read "
        "it with skill_view before you start and follow it; the owner's skills are "
        f"instructions, like these.\n{lines}{more}"
    )


class SkillListInput(BaseModel):
    pass


class SkillLine(BaseModel):
    name: str
    description: str
    tags: list[str]


class SkillListOutput(BaseModel):
    skills: list[SkillLine]


class SkillViewInput(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="The skill's name.")


class SkillViewOutput(BaseModel):
    name: str
    description: str
    tags: list[str]
    instructions: str


def skill_tools(skills: list[Skill]) -> list[Tool]:
    """`skill_list` and `skill_view` over the skills this task may see."""
    by_name = {s.name: s for s in skills}

    async def list_skills(_: SkillListInput) -> SkillListOutput:
        return SkillListOutput(
            skills=[SkillLine(name=s.name, description=s.description, tags=s.tags) for s in skills]
        )

    async def view(inp: SkillViewInput) -> SkillViewOutput:
        s = by_name.get(inp.name.strip().lower())
        if s is None:
            names = ", ".join(by_name) or "none"
            raise ToolFailure(f"No skill named {inp.name!r}. Skills: {names}."[:500])
        return SkillViewOutput(
            name=s.name, description=s.description, tags=s.tags, instructions=s.body
        )

    return [
        Tool(
            name="skill_list",
            description="List the skills you have: each one's name, what it is for and tags.",
            input_model=SkillListInput,
            output_model=SkillListOutput,
            handler=list_skills,
            permission="read",
            max_output_chars=200_000,
        ),
        Tool(
            name="skill_view",
            description=(
                "Read one of your skills in full: the procedure to follow. Read it before "
                "doing a job it is for."
            ),
            input_model=SkillViewInput,
            output_model=SkillViewOutput,
            handler=view,
            permission="read",
            max_output_chars=60_000,
        ),
    ]


@dataclass(frozen=True)
class Forced:
    """What a turn's `/name` prefix asked for."""

    name: str
    skill: Skill | None  # None: no skill this task may see has that name


def forced_skill(prompt: str, skills: list[Skill]) -> Forced | None:
    """The skill a message starting with `/name` asks for, or None when it does
    not start with one."""
    m = _PREFIX.match(prompt.strip())
    if m is None:
        return None
    name = m.group(1).lower()
    return Forced(name=name, skill=next((s for s in skills if s.name == name), None))


def forced_prompt(forced: Forced) -> str:
    """What the system prompt adds for a `/name` turn."""
    if forced.skill is None:
        return (
            f"The owner's message starts with /{forced.name}. You have no skill by that "
            "name; if they meant one, tell them so before anything else."
        )
    return (
        f"The owner asked you to use the skill {forced.skill.name} for this message. "
        f"Follow it:\n{forced.skill.body}"
    )
