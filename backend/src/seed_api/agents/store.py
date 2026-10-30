"""Agent definitions (D-024): a name, what the agent is for, its instructions, its
model and the tools it may use. Each belongs to one owner; names are unique per
owner regardless of case, since the assistant names the agent it delegates to."""

import uuid
from datetime import datetime
from typing import Any, Literal

from psycopg.errors import UniqueViolation
from pydantic import BaseModel

from ..flow.db import Pool

# What an agent may be allowed. run_command needs the sandbox and search_knowledge
# a project; a delegated run gets each only where it exists.
ToolName = Literal["list_files", "read_file", "write_file", "run_command", "search_knowledge"]
TOOL_NAMES: tuple[ToolName, ...] = (
    "list_files",
    "read_file",
    "write_file",
    "run_command",
    "search_knowledge",
)


# How the assistant's delegate tool names each tool when it lists an agent.
AGENT_TOOL_LABELS: dict[str, str] = {
    "list_files": "list files",
    "read_file": "read files",
    "write_file": "write files",
    "run_command": "run commands",
    "search_knowledge": "search project knowledge",
}


class Agent(BaseModel):
    id: uuid.UUID
    owner: str
    name: str
    description: str
    instructions: str
    model: str | None
    tools: list[ToolName]
    # The shared skills it may use (D-033); its private skills are always its own.
    skills: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


# Given once to each owner, the first time they list agents (D-024); plain rows
# they can edit or delete like their own.
STARTERS: tuple[tuple[str, str, str, tuple[ToolName, ...]], ...] = (
    (
        "Researcher",
        "Reads files and project knowledge and reports what they say, with sources.",
        "Answer the question you were given from the workspace files and the project's "
        "knowledge. Say where each fact comes from (file path, or document and part). Say "
        "plainly what you could not find. Do not change files.",
        ("list_files", "read_file", "search_knowledge"),
    ),
    (
        "Coder",
        "Writes and changes code in the workspace and runs commands to check it.",
        "Make the change you were asked for in the workspace. Keep it small and consistent "
        "with the code around it. Run the relevant checks or tests when you can, and report "
        "what you changed, what you ran and the result.",
        ("list_files", "read_file", "write_file", "run_command"),
    ),
    (
        "Reviewer",
        "Checks work against what was asked and reports problems; changes nothing.",
        "Check the work you were pointed to against the request. List concrete problems, "
        "most serious first, with the file and line where you can. Say clearly if you found "
        "none. Do not change files.",
        ("list_files", "read_file"),
    ),
)


class AgentCopy(BaseModel):
    """An agent's definition as a delegated task got it (D-025): later edits to
    the agent do not change a task already handed over."""

    id: uuid.UUID
    name: str
    description: str
    instructions: str
    model: str | None
    tools: list[ToolName]
    skills: list[uuid.UUID] = []  # tasks handed over before skills had none

    @classmethod
    def of(cls, agent: Agent) -> "AgentCopy":
        return cls.model_validate(agent.model_dump(include=set(cls.model_fields)))


class NameTaken(Exception):
    """The owner already has an agent with this name."""


class NoSuchSkill(Exception):
    """A skill the agent is allowed is not one of the owner's shared skills."""


def _ordered(tools: list[ToolName]) -> list[str]:
    """Each allowed tool once, in catalog order."""
    return [t for t in TOOL_NAMES if t in tools]


async def _check_skills(
    conn: Any, owner: str, skills: list[uuid.UUID] | None
) -> list[uuid.UUID] | None:
    """Each skill once; raises NoSuchSkill unless all are the owner's shared skills.
    None stays None."""
    if skills is None:
        return None
    unique = list(dict.fromkeys(skills))
    cur = await conn.execute(
        "SELECT count(*) AS n FROM skills WHERE owner = %s AND agent_id IS NULL AND id = ANY(%s)",
        (owner, unique),
    )
    row = await cur.fetchone()
    if row is None or row["n"] != len(unique):
        raise NoSuchSkill
    return unique


class AgentStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def all(self, owner: str) -> list[Agent]:
        """By name. The first call for an owner adds the starter agents."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "INSERT INTO agent_starters (owner) VALUES (%s) "
                "ON CONFLICT DO NOTHING RETURNING owner",
                (owner,),
            )
            if await cur.fetchone() is not None:
                for name, description, instructions, tools in STARTERS:
                    # A name the owner already uses keeps their agent.
                    await conn.execute(
                        "INSERT INTO agents (id, owner, name, description, instructions, tools) "
                        "VALUES (%s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (owner, lower(name)) DO NOTHING",
                        (uuid.uuid4(), owner, name, description, instructions, list(tools)),
                    )
            cur = await conn.execute(
                "SELECT * FROM agents WHERE owner = %s ORDER BY lower(name), id", (owner,)
            )
            return [Agent.model_validate(r) for r in await cur.fetchall()]

    async def named(self, owner: str, name: str) -> Agent | None:
        """The owner's agent with this name, ignoring case."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM agents WHERE owner = %s AND lower(name) = lower(%s)",
                (owner, " ".join(name.split())),
            )
            row = await cur.fetchone()
        return Agent.model_validate(row) if row else None

    async def get(self, owner: str, agent_id: uuid.UUID) -> Agent | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM agents WHERE id = %s AND owner = %s", (agent_id, owner)
            )
            row = await cur.fetchone()
        return Agent.model_validate(row) if row else None

    async def create(
        self,
        *,
        owner: str,
        name: str,
        description: str,
        instructions: str,
        model: str | None,
        tools: list[ToolName],
        skills: list[uuid.UUID] | None = None,
    ) -> Agent:
        """Raises NameTaken or NoSuchSkill."""
        try:
            async with self.pool.connection() as conn:
                allowed = await _check_skills(conn, owner, skills)
                cur = await conn.execute(
                    "INSERT INTO agents "
                    "(id, owner, name, description, instructions, model, tools, skills) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                    (
                        uuid.uuid4(),
                        owner,
                        name,
                        description,
                        instructions,
                        model,
                        _ordered(tools),
                        allowed or [],
                    ),
                )
                row = await cur.fetchone()
        except UniqueViolation:
            raise NameTaken from None
        assert row is not None  # noqa: S101 - RETURNING always yields the row
        return Agent.model_validate(row)

    async def update(
        self,
        agent_id: uuid.UUID,
        *,
        owner: str,
        name: str,
        description: str,
        instructions: str,
        model: str | None,
        tools: list[ToolName],
        skills: list[uuid.UUID] | None = None,
    ) -> Agent | None:
        """Replace the definition (`skills` None keeps the list). None when there
        is no such agent; raises NameTaken or NoSuchSkill."""
        try:
            async with self.pool.connection() as conn:
                allowed = await _check_skills(conn, owner, skills)
                cur = await conn.execute(
                    "UPDATE agents SET name = %s, description = %s, instructions = %s, "
                    "model = %s, tools = %s, skills = coalesce(%s, skills), updated_at = now() "
                    "WHERE id = %s AND owner = %s RETURNING *",
                    (
                        name,
                        description,
                        instructions,
                        model,
                        _ordered(tools),
                        allowed,
                        agent_id,
                        owner,
                    ),
                )
                row = await cur.fetchone()
        except UniqueViolation:
            raise NameTaken from None
        return Agent.model_validate(row) if row else None

    async def delete(self, owner: str, agent_id: uuid.UUID) -> bool:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM agents WHERE id = %s AND owner = %s RETURNING id", (agent_id, owner)
            )
            return await cur.fetchone() is not None
