"""The sandbox service: `uvicorn seed_api.sandbox.server:app --port 8100 --loop asyncio`.

Only the worker can reach it (an internal Docker network with no route out).
The server itself never reads or writes workspace files: every operation runs
as the task's user through `runner`, so the kernel enforces the boundaries.
"""

import asyncio
import logging
import os
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from pydantic import ValidationError

from ..config import Settings, get_settings
from ..core.workspace_tools import MAX_FILE_BYTES
from ..errors import ApiError, install_error_handlers
from . import runner
from .protocol import ExecRequest, ExecResult, FileRequest, FileResult

log = logging.getLogger("seed.sandbox")
MB = 1024 * 1024
# A full read_file result as JSON, with room for escaping.
FILEOPS_MAX_OUTPUT = 8 * MAX_FILE_BYTES


def create_sandbox_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    root = Path(settings.sandbox_root)
    limits = runner.Limits(
        memory_bytes=settings.sandbox_memory_mb * MB,
        cpu_seconds=settings.sandbox_cpu_seconds,
        max_processes=settings.sandbox_max_processes,
        max_file_bytes=settings.sandbox_max_file_mb * MB,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if type(asyncio.get_running_loop()).__module__.startswith("uvloop"):
            raise RuntimeError("Run the sandbox with `--loop asyncio`: uvloop cannot switch users.")
        if settings.sandbox_isolate_users and os.geteuid() != 0:
            raise RuntimeError(
                "The sandbox runs each task as its own user, which needs root in the "
                "container. Set SEED_SANDBOX_ISOLATE_USERS=false only for tests."
            )
        if not root.is_dir():
            raise RuntimeError(f"Sandbox root {root} does not exist.")
        if not settings.sandbox_isolate_users:
            log.warning("sandbox user isolation is OFF: tasks share one user")
        yield

    app = FastAPI(title="SEED sandbox", docs_url=None, redoc_url=None, lifespan=lifespan)
    install_error_handlers(app)

    def workspace(task_id: uuid.UUID) -> tuple[Path, int | None]:
        path = root / str(task_id)
        if not settings.sandbox_isolate_users:
            path.mkdir(mode=0o700, exist_ok=True)
            return path, None
        uid = runner.task_uid(task_id)
        try:
            path.mkdir(mode=0o700)
            os.chown(path, uid, uid)
        except FileExistsError:
            if path.stat().st_uid != uid:
                raise ApiError(500, "workspace_owner", "Workspace has the wrong owner.") from None
        return path, uid

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/workspaces/{task_id}/exec", response_model=ExecResult)
    async def exec_command(task_id: uuid.UUID, body: ExecRequest) -> ExecResult:
        path, uid = workspace(task_id)
        return await runner.run(
            ["/bin/sh", "-c", body.command],
            cwd=path,
            uid=uid,
            stdin=body.stdin.encode(),
            timeout_s=min(body.timeout_s, settings.sandbox_command_timeout_seconds),
            limits=limits,
        )

    @app.post("/v1/workspaces/{task_id}/files", response_model=FileResult)
    async def file_op(task_id: uuid.UUID, body: FileRequest) -> FileResult:
        path, uid = workspace(task_id)
        done = await runner.run(
            [sys.executable, "-I", "-m", "seed_api.sandbox.fileops"],
            cwd=path,
            uid=uid,
            stdin=body.model_dump_json().encode(),
            timeout_s=30,
            limits=limits,
            max_output=FILEOPS_MAX_OUTPUT,
        )
        try:
            return FileResult.model_validate_json(done.stdout)
        except ValidationError:
            log.error("fileops failed: exit=%s stderr=%s", done.exit_code, done.stderr[-500:])
            raise ApiError(500, "file_op_failed", "The file operation did not complete.") from None

    return app


app = create_sandbox_app()
