"""Whole-workspace file operations for saving and restoring artifacts (ADR-0014).

Pure functions on a directory, used by the sandbox (run as the task's user) and
by the worker when no sandbox is configured. Paths stay inside the workspace by
the same rules as the agent's file tools; a snapshot lists no symlinks.
"""

import hashlib
from pathlib import Path

from pydantic import BaseModel

from ..core.tools import ToolFailure
from ..core.workspace_tools import resolve

# A file larger than this is not saved; the event that reports the save names it.
MAX_ARTIFACT_BYTES = 1024 * 1024
# A workspace with more files than this is saved in part, and deletions are not
# recorded, since a missing file may only be past the cut.
MAX_SNAPSHOT_FILES = 500


class FileStat(BaseModel):
    path: str
    size: int
    # None when the file is over MAX_ARTIFACT_BYTES.
    sha256: str | None


class Snapshot(BaseModel):
    files: list[FileStat]
    truncated: bool


def snapshot(root: Path) -> Snapshot:
    """Every regular file in the workspace, in path order, with its hash."""
    files: list[FileStat] = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        if len(files) >= MAX_SNAPSHOT_FILES:
            return Snapshot(files=files, truncated=True)
        size = p.stat().st_size
        digest = hashlib.sha256(p.read_bytes()).hexdigest() if size <= MAX_ARTIFACT_BYTES else None
        files.append(FileStat(path=p.relative_to(root).as_posix(), size=size, sha256=digest))
    return Snapshot(files=files, truncated=False)


def read_bytes(root: Path, rel: str) -> bytes:
    path = resolve(root, rel)
    if not path.is_file():
        raise ToolFailure(f"No such file: {rel}")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ToolFailure("File is larger than the artifact limit.")
    return path.read_bytes()


def write_bytes(root: Path, rel: str, data: bytes) -> None:
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ToolFailure("File is larger than the artifact limit.")
    path = resolve(root, rel)
    if path == root or path.is_dir():
        raise ToolFailure("Path is a directory.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
