"""Saving a workspace's changed files as artifact versions, and restoring them."""

import uuid

from pydantic import BaseModel

from ..core.tools import ToolFailure
from .store import ArtifactStore, Change, Saved
from .workspace import WorkspaceFiles


class Skipped(BaseModel):
    path: str
    # too_large: over the artifact limit; unreadable: changed or vanished mid-save.
    reason: str


class SaveReport(BaseModel):
    saved: list[Saved]
    skipped: list[Skipped]
    # More files than one save covers; the rest were not looked at.
    truncated: bool


async def save_changes(
    files: WorkspaceFiles,
    store: ArtifactStore,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    task_id: uuid.UUID,
) -> SaveReport:
    """Add a version for every file that is new, changed or deleted since the last save."""
    snap = await files.snapshot()
    known = await store.latest(workspace_id)
    changes: list[Change] = []
    skipped: list[Skipped] = []
    for f in snap.files:
        if f.sha256 is None:
            skipped.append(Skipped(path=f.path, reason="too_large"))
            continue
        if known.get(f.path) == f.sha256:
            continue
        try:
            data = await files.read(f.path)
        except ToolFailure:
            skipped.append(Skipped(path=f.path, reason="unreadable"))
            continue
        changes.append(Change(path=f.path, sha256=await store.put_blob(data), size=len(data)))
    if not snap.truncated:  # a cut-off listing cannot tell a deleted file from an unseen one
        present = {f.path for f in snap.files}
        changes += [
            Change(path=p, sha256=None, size=None)
            for p, sha in sorted(known.items())
            if sha is not None and p not in present
        ]
    saved = await store.record(
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        task_id=task_id,
        changes=changes,
    )
    return SaveReport(saved=saved, skipped=skipped, truncated=snap.truncated)


async def restore(files: WorkspaceFiles, store: ArtifactStore, workspace_id: uuid.UUID) -> int:
    """Put the saved files back into an empty workspace (after a sandbox restart).
    A workspace with any file in it is left alone. Returns how many were written."""
    current = {p: sha for p, sha in (await store.latest(workspace_id)).items() if sha}
    if not current or (await files.snapshot()).files:
        return 0
    for path, sha in sorted(current.items()):
        await files.write(path, await store.read_blob(sha))
    return len(current)
