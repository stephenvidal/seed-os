"""A task workspace's files as the worker sees them: on the sandbox or on local disk."""

import asyncio
import base64
import uuid
from pathlib import Path
from typing import Protocol

from ..sandbox.client import SandboxClient
from .files import Snapshot, read_bytes, snapshot, write_bytes


class WorkspaceFiles(Protocol):
    async def snapshot(self) -> Snapshot: ...
    async def read(self, path: str) -> bytes: ...
    async def write(self, path: str, data: bytes) -> None: ...


class LocalFiles:
    """A directory on the worker's own disk (no sandbox configured)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def snapshot(self) -> Snapshot:
        return await asyncio.to_thread(snapshot, self.root)

    async def read(self, path: str) -> bytes:
        return await asyncio.to_thread(read_bytes, self.root, path)

    async def write(self, path: str, data: bytes) -> None:
        await asyncio.to_thread(write_bytes, self.root, path, data)


class SandboxFiles:
    """A workspace in the sandbox, read and written as the task's own user."""

    def __init__(self, sandbox: SandboxClient, workspace_id: uuid.UUID) -> None:
        self.sandbox = sandbox
        self.workspace_id = workspace_id

    async def snapshot(self) -> Snapshot:
        return Snapshot.model_validate(await self.sandbox.file(self.workspace_id, op="snapshot"))

    async def read(self, path: str) -> bytes:
        out = await self.sandbox.file(self.workspace_id, op="read_bytes", path=path)
        return base64.b64decode(out["data"], validate=True)

    async def write(self, path: str, data: bytes) -> None:
        await self.sandbox.file(
            self.workspace_id,
            op="write_bytes",
            path=path,
            data=base64.b64encode(data).decode(),
        )
