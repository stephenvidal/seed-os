"""Skills (D-033): procedures the owner saves, each a name, what it is for, tags
and the instructions themselves, as in a Hermes Agent SKILL.md. Each belongs to
one owner; a skill with an agent is private to that agent. Names are unique per
owner across both, so `/name` in a message is never ambiguous."""

import uuid
from datetime import datetime

from psycopg.errors import ForeignKeyViolation, UniqueViolation
from pydantic import BaseModel

from ..agents.store import AgentCopy
from ..flow.db import Pool


class Skill(BaseModel):
    id: uuid.UUID
    owner: str
    # Private to this agent; None: shared with SEED and the agents allowed it.
    agent_id: uuid.UUID | None
    name: str
    description: str
    tags: list[str]
    body: str
    created_at: datetime
    updated_at: datetime


class NameTaken(Exception):
    """The owner already has a skill with this name."""


class NoSuchAgent(Exception):
    """The skill names an agent the owner does not have."""


class SkillStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def all(self, owner: str) -> list[Skill]:
        """By name."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM skills WHERE owner = %s ORDER BY name", (owner,)
            )
            return [Skill.model_validate(r) for r in await cur.fetchall()]

    async def visible(self, owner: str, agent: AgentCopy | None) -> list[Skill]:
        """The skills a task may see, by name: SEED's own tasks see the shared
        skills; an agent's task sees the shared skills it is allowed and its own."""
        async with self.pool.connection() as conn:
            if agent is None:
                cur = await conn.execute(
                    "SELECT * FROM skills WHERE owner = %s AND agent_id IS NULL ORDER BY name",
                    (owner,),
                )
            else:
                cur = await conn.execute(
                    "SELECT * FROM skills WHERE owner = %s "
                    "AND (agent_id = %s OR (agent_id IS NULL AND id = ANY(%s))) ORDER BY name",
                    (owner, agent.id, agent.skills),
                )
            return [Skill.model_validate(r) for r in await cur.fetchall()]

    async def get(self, owner: str, skill_id: uuid.UUID) -> Skill | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM skills WHERE id = %s AND owner = %s", (skill_id, owner)
            )
            row = await cur.fetchone()
        return Skill.model_validate(row) if row else None

    async def create(
        self,
        *,
        owner: str,
        agent_id: uuid.UUID | None,
        name: str,
        description: str,
        tags: list[str],
        body: str,
    ) -> Skill:
        """Raises NameTaken or NoSuchAgent."""
        try:
            async with self.pool.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO skills (id, owner, agent_id, name, description, tags, body) "
                    "SELECT %s, %s, %s, %s, %s, %s, %s "
                    "WHERE %s::uuid IS NULL "
                    "   OR EXISTS (SELECT 1 FROM agents WHERE id = %s AND owner = %s) "
                    "RETURNING *",
                    (uuid.uuid4(), owner, agent_id, name, description, tags, body)
                    + (agent_id, agent_id, owner),
                )
                row = await cur.fetchone()
        except UniqueViolation:
            raise NameTaken from None
        except ForeignKeyViolation:  # the agent was deleted meanwhile
            raise NoSuchAgent from None
        if row is None:
            raise NoSuchAgent
        return Skill.model_validate(row)

    async def update(
        self,
        skill_id: uuid.UUID,
        *,
        owner: str,
        agent_id: uuid.UUID | None,
        name: str,
        description: str,
        tags: list[str],
        body: str,
    ) -> Skill | None:
        """Replace the skill. None when there is no such skill; raises NameTaken
        or NoSuchAgent."""
        async with self.pool.connection() as conn:
            if agent_id is not None:
                cur = await conn.execute(
                    "SELECT 1 FROM agents WHERE id = %s AND owner = %s", (agent_id, owner)
                )
                if await cur.fetchone() is None:
                    raise NoSuchAgent
            try:
                cur = await conn.execute(
                    "UPDATE skills SET agent_id = %s, name = %s, description = %s, tags = %s, "
                    "body = %s, updated_at = now() WHERE id = %s AND owner = %s RETURNING *",
                    (agent_id, name, description, tags, body, skill_id, owner),
                )
            except UniqueViolation:
                raise NameTaken from None
            except ForeignKeyViolation:  # the agent was deleted meanwhile
                raise NoSuchAgent from None
            row = await cur.fetchone()
            if row is not None and agent_id is not None:  # private now: no agent shares it
                await conn.execute(
                    "UPDATE agents SET skills = array_remove(skills, %s) "
                    "WHERE owner = %s AND %s = ANY(skills)",
                    (skill_id, owner, skill_id),
                )
        return Skill.model_validate(row) if row else None

    async def delete(self, owner: str, skill_id: uuid.UUID) -> bool:
        """Also takes it off the lists of the agents allowed it."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "DELETE FROM skills WHERE id = %s AND owner = %s RETURNING id", (skill_id, owner)
            )
            if await cur.fetchone() is None:
                return False
            await conn.execute(
                "UPDATE agents SET skills = array_remove(skills, %s) "
                "WHERE owner = %s AND %s = ANY(skills)",
                (skill_id, owner, skill_id),
            )
            return True
