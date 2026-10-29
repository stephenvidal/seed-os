"""Studio API: saved artifacts, their versions and content, and sandboxed previews.

Content is served so a browser never runs it with the app's authority (ADR-0015):
every response carries a CSP that sandboxes it, the version endpoint allows no
scripts at all, and HTML previews come from a separate path, through a short-lived
link, into an opaque origin that cannot reach the network.
"""

import mimetypes
import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from ..errors import ApiError
from ..flow.api import AdminOnly
from .store import Artifact, ArtifactStore, Version

router = APIRouter(prefix="/api/v1/artifacts", tags=["studio"])
previews = APIRouter(prefix="/api/v1/previews", tags=["studio"])

PREVIEW_TTL_SECONDS = 3600
# A saved version opened directly: shown, never run.
CONTENT_CSP = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
# A preview page: its own scripts run, in an opaque origin with no network access,
# and it may load only other files of the same preview.
PREVIEW_CSP = (
    "sandbox allow-scripts allow-modals; default-src 'self' data: blob:; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
    "style-src 'self' 'unsafe-inline' data:; connect-src 'none'; form-action 'none'; "
    "base-uri 'none'; frame-ancestors 'self'"
)
_TEXT = {"application/json", "application/javascript", "application/xml", "image/svg+xml"}


def media_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path, strict=False)
    kind = guessed or "application/octet-stream"
    return f"{kind}; charset=utf-8" if kind.startswith("text/") or kind in _TEXT else kind


def get_store(request: Request) -> ArtifactStore:
    store: ArtifactStore | None = getattr(request.app.state, "artifact_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Artifacts need a database. Set SEED_DATABASE_URL."
        )
    return store


StoreDep = Annotated[ArtifactStore, Depends(get_store)]


class VersionView(BaseModel):
    version: int
    task_id: uuid.UUID | None
    size: int | None
    deleted: bool
    created_at: datetime

    @classmethod
    def of(cls, v: Version) -> "VersionView":
        return cls(
            version=v.version,
            task_id=v.task_id,
            size=v.size,
            deleted=v.deleted,
            created_at=v.created_at,
        )


class ArtifactView(BaseModel):
    id: uuid.UUID
    path: str
    media_type: str
    conversation_id: uuid.UUID | None
    # The conversation's title, or the lone task's.
    source_title: str | None
    # Set for a lone task's files: the task whose workspace it is.
    task_id: uuid.UUID | None
    versions: int
    latest: VersionView
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, a: Artifact) -> "ArtifactView":
        return cls(
            id=a.id,
            path=a.path,
            media_type=media_type(a.path),
            conversation_id=a.conversation_id,
            source_title=a.source_title,
            task_id=None if a.conversation_id else a.workspace_id,
            versions=a.versions,
            latest=VersionView.of(a.latest),
            created_at=a.created_at,
            updated_at=a.updated_at,
        )


class ArtifactDetail(BaseModel):
    artifact: ArtifactView
    # Newest first.
    versions: list[VersionView]


class Preview(BaseModel):
    url: str
    expires_in: int


async def _artifact(store: ArtifactStore, artifact_id: uuid.UUID) -> tuple[Artifact, list[Version]]:
    found = await store.get(artifact_id)
    if found is None:
        raise ApiError(404, "not_found", "No such artifact.")
    return found


async def _content(store: ArtifactStore, sha256: str) -> bytes:
    if store.root is None:
        raise ApiError(
            503, "artifacts_not_configured", "File content needs SEED_ARTIFACT_ROOT on the API."
        )
    try:
        return await store.read_blob(sha256)
    except OSError:
        raise ApiError(500, "content_missing", "The saved content could not be read.") from None


@router.get("", response_model=list[ArtifactView])
async def list_artifacts(
    _: AdminOnly,
    store: StoreDep,
    conversation_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[ArtifactView]:
    """Saved files, most recently changed first; all users' (like the task list).
    `conversation_id` or `project_id` narrows them to one chat or one project's chats."""
    found = await store.find(conversation_id=conversation_id, project_id=project_id, limit=limit)
    return [ArtifactView.of(a) for a in found]


@router.get("/{artifact_id}", response_model=ArtifactDetail)
async def get_artifact(artifact_id: uuid.UUID, _: AdminOnly, store: StoreDep) -> ArtifactDetail:
    artifact, versions = await _artifact(store, artifact_id)
    return ArtifactDetail(
        artifact=ArtifactView.of(artifact), versions=[VersionView.of(v) for v in versions]
    )


@router.get("/{artifact_id}/versions/{version}/content")
async def version_content(
    artifact_id: uuid.UUID,
    version: int,
    _: AdminOnly,
    store: StoreDep,
    download: bool = False,
) -> Response:
    """One version's bytes. Shown inline (scripts never run) or, with
    `?download=true`, as an attachment."""
    artifact, versions = await _artifact(store, artifact_id)
    v = next((x for x in versions if x.version == version), None)
    if v is None:
        raise ApiError(404, "not_found", "No such version.")
    if v.sha256 is None:
        raise ApiError(410, "deleted", "The file was deleted in this version.")
    name = quote(artifact.path.rsplit("/", 1)[-1])
    return Response(
        await _content(store, v.sha256),
        media_type=media_type(artifact.path),
        headers={
            "Content-Disposition": f"{'attachment' if download else 'inline'}; "
            f"filename*=UTF-8''{name}",
            "Content-Security-Policy": CONTENT_CSP,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.post("/{artifact_id}/preview", response_model=Preview, status_code=201)
async def create_preview(artifact_id: uuid.UUID, principal: AdminOnly, store: StoreDep) -> Preview:
    """A link that renders this file, with the other files of its workspace beside
    it (latest versions), in a sandbox. It works for an hour."""
    artifact, _ = await _artifact(store, artifact_id)
    if artifact.latest.deleted:
        raise ApiError(410, "deleted", "The file is deleted; preview an earlier version's text.")
    token = await store.create_preview(
        artifact.workspace_id, created_by=principal.username, ttl_seconds=PREVIEW_TTL_SECONDS
    )
    path = quote(artifact.path)
    return Preview(url=f"{previews.prefix}/{token}/{path}", expires_in=PREVIEW_TTL_SECONDS)


@previews.get("/{token}/{path:path}")
async def preview_file(token: str, path: str, store: StoreDep) -> Response:
    """No session: the sandboxed page sends no cookies, so the link is the permission."""
    sha = await store.preview_file(token, path)
    if sha is None:
        raise ApiError(404, "not_found", "No such file, or the preview link has expired.")
    return Response(
        await _content(store, sha),
        media_type=media_type(path),
        headers={
            "Content-Security-Policy": PREVIEW_CSP,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        },
    )
