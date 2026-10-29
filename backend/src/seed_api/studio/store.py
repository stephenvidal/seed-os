"""Artifact storage (ADR-0014): content on disk under its SHA-256, versions in Postgres.

Only the worker writes content. A blob is written to a temporary name and renamed
into place, so a reader never sees half a file, and identical content is stored
once. The API reads it for Studio, and issues preview links (ADR-0015).
"""

import asyncio
import hashlib
import os
import secrets
import uuid
from datetime import datetime
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


class Version(BaseModel):
    version: int
    task_id: uuid.UUID | None
    sha256: str | None
    size: int | None
    created_at: datetime

    @property
    def deleted(self) -> bool:
        return self.sha256 is None


class Artifact(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    conversation_id: uuid.UUID | None
    source_title: str | None
    path: str
    created_at: datetime
    updated_at: datetime
    versions: int
    latest: Version


# The latest version of each artifact, with the title of its conversation, or of
# the task for a lone task's files.
_ARTIFACTS = """
SELECT a.id, a.workspace_id, a.conversation_id, coalesce(c.title, t.title) AS source_title,
       a.path,
       a.created_at, a.updated_at, l.version, l.task_id, l.sha256, l.size,
       l.created_at AS version_at, l.n AS versions
FROM artifacts a
LEFT JOIN conversations c ON c.id = a.conversation_id
LEFT JOIN tasks t ON a.conversation_id IS NULL AND t.id = a.workspace_id
JOIN LATERAL (
    SELECT v.*, count(*) OVER () AS n FROM artifact_versions v
    WHERE v.artifact_id = a.id ORDER BY v.version DESC LIMIT 1
) l ON true
"""


def _artifact(row: dict[str, object]) -> Artifact:
    return Artifact.model_validate(
        {
            **row,
            "latest": {
                "version": row["version"],
                "task_id": row["task_id"],
                "sha256": row["sha256"],
                "size": row["size"],
                "created_at": row["version_at"],
            },
        }
    )


class ArtifactStore:
    def __init__(self, pool: Pool, root: Path | None) -> None:
        self.pool = pool
        # None: no content store configured (the API can still list versions).
        self.root = root

    def blob_path(self, sha256: str) -> Path:
        if self.root is None:
            raise RuntimeError("No artifact root configured.")
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

    async def find(
        self,
        *,
        conversation_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 200,
    ) -> list[Artifact]:
        """Artifacts, most recently changed first; of one conversation, or of the
        conversations in one project, when given."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                _ARTIFACTS + "WHERE (%(c)s::uuid IS NULL OR a.conversation_id = %(c)s) "
                "AND (%(p)s::uuid IS NULL OR c.project_id = %(p)s) "
                "ORDER BY a.updated_at DESC, a.path LIMIT %(limit)s",
                {"c": conversation_id, "p": project_id, "limit": limit},
            )
            return [_artifact(r) for r in await cur.fetchall()]

    async def get(self, artifact_id: uuid.UUID) -> tuple[Artifact, list[Version]] | None:
        """One artifact and all its versions, newest first."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(_ARTIFACTS + "WHERE a.id = %s", (artifact_id,))
            row = await cur.fetchone()
            if row is None:
                return None
            cur = await conn.execute(
                "SELECT version, task_id, sha256, size, created_at FROM artifact_versions "
                "WHERE artifact_id = %s ORDER BY version DESC",
                (artifact_id,),
            )
            return _artifact(row), [Version.model_validate(r) for r in await cur.fetchall()]

    async def create_preview(
        self, workspace_id: uuid.UUID, *, created_by: str, ttl_seconds: int
    ) -> str:
        """A new preview token for a workspace. Expired tokens are removed here."""
        token = secrets.token_urlsafe(32)
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("DELETE FROM artifact_previews WHERE expires_at < now()")
            await conn.execute(
                "INSERT INTO artifact_previews (token_hash, workspace_id, created_by, expires_at) "
                "VALUES (%s, %s, %s, now() + make_interval(secs => %s))",
                (_digest(token), workspace_id, created_by, ttl_seconds),
            )
        return token

    async def preview_file(self, token: str, path: str) -> str | None:
        """The current content hash of `path` in the token's workspace, if the token
        is live and the file exists (not deleted)."""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT v.sha256 FROM artifact_previews p "
                "JOIN artifacts a ON a.workspace_id = p.workspace_id AND a.path = %s "
                "JOIN LATERAL (SELECT sha256 FROM artifact_versions "
                "  WHERE artifact_id = a.id ORDER BY version DESC LIMIT 1) v ON true "
                "WHERE p.token_hash = %s AND p.expires_at > now()",
                (path, _digest(token)),
            )
            row = await cur.fetchone()
            return row["sha256"] if row else None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
