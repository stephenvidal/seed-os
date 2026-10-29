"""Artifact storage (ADR-0014): content on disk under its SHA-256, versions in Postgres.

Only the worker writes. A blob is written to a temporary name and renamed into
place, so a reader never sees half a file, and identical content is stored once.
"""

import asyncio
import hashlib
import os
import uuid
from pathlib import Path

from pydantic import BaseModel

from ..flow.db import Pool


class Saved(BaseModel):
    path: str
    version: int
    deleted: bool


class Change(BaseModel):
    path: str
    # None records a deletion.
    sha256: str | None
    size: int | None


class ArtifactStore:
    def __init__(self, pool: Pool, root: Path) -> None:
        self.pool = pool
        self.root = root

    def blob_path(self, sha256: str) -> Path:
        return self.root / "blobs" / sha256[:2] / sha256

    async def put_blob(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self.blob_path(sha)

        def write() -> None:
            if path.exists():
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{sha}.{uuid.uuid4().hex}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)

        await asyncio.to_thread(write)
        return sha

    async def read_blob(self, sha256: str) -> bytes:
        return await asyncio.to_thread(self.blob_path(sha256).read_bytes)

    async def latest(self, workspace_id: uuid.UUID) -> dict[str, str | None]:
        """Each saved path in a workspace and its current content (None: deleted)."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT DISTINCT ON (a.id) a.path, v.sha256 FROM artifacts a "
                "JOIN artifact_versions v ON v.artifact_id = a.id "
                "WHERE a.workspace_id = %s ORDER BY a.id, v.version DESC",
                (workspace_id,),
            )
            return {row["path"]: row["sha256"] for row in await cur.fetchall()}

    async def record(
        self,
        *,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        task_id: uuid.UUID,
        changes: list[Change],
    ) -> list[Saved]:
        """Add one version per change, all or none."""
        saved: list[Saved] = []
        async with self.pool.connection() as conn, conn.transaction():
            for c in changes:
                cur = await conn.execute(
                    "INSERT INTO artifacts (id, workspace_id, conversation_id, path) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (workspace_id, path) "
                    "DO UPDATE SET updated_at = now() RETURNING id",
                    (uuid.uuid4(), workspace_id, conversation_id, c.path),
                )
                row = await cur.fetchone()
                assert row is not None  # noqa: S101 - RETURNING always yields the row
                cur = await conn.execute(
                    "INSERT INTO artifact_versions (artifact_id, version, task_id, sha256, size) "
                    "SELECT %(id)s, coalesce(max(version), 0) + 1, %(task)s, %(sha)s, %(size)s "
                    "FROM artifact_versions WHERE artifact_id = %(id)s RETURNING version",
                    {"id": row["id"], "task": task_id, "sha": c.sha256, "size": c.size},
                )
                v = await cur.fetchone()
                assert v is not None  # noqa: S101 - RETURNING always yields the row
                saved.append(Saved(path=c.path, version=v["version"], deleted=c.sha256 is None))
        return saved
