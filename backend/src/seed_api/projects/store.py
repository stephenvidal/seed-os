"""Projects (D-017): a name and instructions over a group of the owner's
conversations. A conversation belongs to at most one project; each turn copies the
project's instructions when it is sent (see chat/store.py)."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from ..flow.db import Pool


class Project(BaseModel):
    id: uuid.UUID
    owner: str
    name: str
    instructions: str
    created_at: datetime
    updated_at: datetime


class ProjectSummary(Project):
    conversations: int
    # Memory notes the agent proposed that wait for the owner.
    proposed_memories: int
    documents: int


_SUMMARY = """
SELECT p.*, (SELECT count(*) FROM conversations c WHERE c.project_id = p.id) AS conversations,
       (SELECT count(*) FROM project_memories m
        WHERE m.project_id = p.id AND m.status = 'proposed') AS proposed_memories,
       (SELECT count(*) FROM knowledge_documents d WHERE d.project_id = p.id) AS documents
FROM projects p
"""


class ProjectStore:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def create(self, *, owner: str, name: str, instructions: str) -> ProjectSummary:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO projects (id, owner, name, instructions) VALUES (%s, %s, %s, %s) "
                "RETURNING *, 0 AS conversations, 0 AS proposed_memories, 0 AS documents",
                (uuid.uuid4(), owner, name, instructions),
            )
            row = await cur.fetchone()
        assert row is not None  # noqa: S101 - RETURNING always yields the row
        return ProjectSummary.model_validate(row)

    async def list(self, owner: str) -> list[ProjectSummary]:
        """Most recently changed first."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                _SUMMARY + "WHERE p.owner = %s ORDER BY p.updated_at DESC, p.id", (owner,)
            )
            rows = await cur.fetchall()
        return [ProjectSummary.model_validate(r) for r in rows]

    async def get(self, owner: str, project_id: uuid.UUID) -> ProjectSummary | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                _SUMMARY + "WHERE p.id = %s AND p.owner = %s", (project_id, owner)
            )
            row = await cur.fetchone()
        return ProjectSummary.model_validate(row) if row else None

    async def update(
        self,
        project_id: uuid.UUID,
        *,
        owner: str,
        name: str | None,
        instructions: str | None,
    ) -> ProjectSummary | None:
        """Change the name, the instructions, or both. New instructions apply to
        turns sent from now on. None when there is no such project."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE projects SET name = coalesce(%s, name), "
                "instructions = coalesce(%s, instructions), updated_at = now() "
                "WHERE id = %s AND owner = %s RETURNING id",
                (name, instructions, project_id, owner),
            )
            if await cur.fetchone() is None:
                return None
        return await self.get(owner, project_id)

    async def delete(self, project_id: uuid.UUID, *, owner: str) -> int | None:
        """Delete a project. Its conversations stay and leave the project; returns
        how many there were, or None when there is no such project."""
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT count(*) AS n FROM conversations WHERE project_id = %s", (project_id,)
            )
            counted = await cur.fetchone()
            cur = await conn.execute(
                "DELETE FROM projects WHERE id = %s AND owner = %s RETURNING id",
                (project_id, owner),
            )
            if await cur.fetchone() is None:
                return None
        return int(counted["n"]) if counted else 0
