"""Worker-side tools backed by the sandbox: files and shell commands in one workspace."""

import uuid
from typing import Any

import httpx
from pydantic import BaseModel, Field

from ..core.tools import Tool, ToolFailure
from ..core.workspace_tools import (
    LIST_DESCRIPTION,
    READ_DESCRIPTION,
    WRITE_DESCRIPTION,
    ListOutput,
    PathInput,
    ReadInput,
    ReadOutput,
    WriteInput,
    WriteOutput,
)
from .protocol import MAX_COMMAND_CHARS, MAX_STDIN_BYTES, ExecRequest, ExecResult, FileResult


class SandboxClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    @classmethod
    def connect(cls, base_url: str, timeout_s: float) -> "SandboxClient":
        return cls(httpx.AsyncClient(base_url=base_url, timeout=timeout_s))

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            r = await self.http.post(path, json=body)
        except httpx.HTTPError as e:
            raise ToolFailure(f"The sandbox is unreachable ({type(e).__name__}).") from e
        if r.status_code != 200:
            try:
                message = r.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = f"HTTP {r.status_code}"
            raise ToolFailure(f"Sandbox error: {message}")
        data: dict[str, Any] = r.json()
        return data

    async def exec(self, workspace_id: uuid.UUID, req: ExecRequest) -> ExecResult:
        data = await self._post(f"/v1/workspaces/{workspace_id}/exec", req.model_dump())
        return ExecResult.model_validate(data)

    async def file(self, workspace_id: uuid.UUID, **body: Any) -> dict[str, Any]:
        res = FileResult.model_validate(
            await self._post(f"/v1/workspaces/{workspace_id}/files", body)
        )
        if not res.ok or res.result is None:
            raise ToolFailure(res.error or "The file operation failed.")
        return res.result


class CommandInput(BaseModel):
    command: str = Field(
        min_length=1, max_length=MAX_COMMAND_CHARS, description="Shell command (/bin/sh -c)"
    )
    timeout_s: int = Field(default=30, ge=1, le=600, description="Seconds before it is killed")
    stdin: str = Field(default="", max_length=MAX_STDIN_BYTES, description="Text sent to stdin")


def sandbox_tools(
    client: SandboxClient, workspace_id: uuid.UUID, max_timeout_s: float
) -> list[Tool]:
    async def list_files(inp: PathInput) -> ListOutput:
        return ListOutput.model_validate(await client.file(workspace_id, op="list", path=inp.path))

    async def read_file(inp: ReadInput) -> ReadOutput:
        return ReadOutput.model_validate(await client.file(workspace_id, op="read", path=inp.path))

    async def write_file(inp: WriteInput) -> WriteOutput:
        return WriteOutput.model_validate(
            await client.file(workspace_id, op="write", path=inp.path, content=inp.content)
        )

    async def run_command(inp: CommandInput) -> ExecResult:
        timeout = min(float(inp.timeout_s), max_timeout_s)
        return await client.exec(
            workspace_id, ExecRequest(command=inp.command, stdin=inp.stdin, timeout_s=timeout)
        )

    return [
        Tool("list_files", LIST_DESCRIPTION, PathInput, ListOutput, list_files, "read", 30),
        Tool("read_file", READ_DESCRIPTION, ReadInput, ReadOutput, read_file, "read", 30),
        Tool("write_file", WRITE_DESCRIPTION, WriteInput, WriteOutput, write_file, "write", 30),
        Tool(
            name="run_command",
            description=(
                "Run a shell command in the workspace, in an isolated sandbox with no "
                "network access. Returns exit code, stdout and stderr (each cut at 8 KiB). "
                f"Commands are killed after timeout_s (at most {int(max_timeout_s)} s); "
                "background processes do not survive the command."
            ),
            input_model=CommandInput,
            output_model=ExecResult,
            handler=run_command,
            permission="exec",
            timeout_s=max_timeout_s + 15,
        ),
    ]
