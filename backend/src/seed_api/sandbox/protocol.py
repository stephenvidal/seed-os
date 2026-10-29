"""Requests and results exchanged between the worker and the sandbox."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.workspace_tools import MAX_FILE_BYTES

MAX_COMMAND_CHARS = 10_000
MAX_STDIN_BYTES = 256 * 1024
# Per stream. The model reads the result, so a little goes a long way.
MAX_OUTPUT_BYTES = 8 * 1024


class ExecRequest(BaseModel):
    command: str = Field(min_length=1, max_length=MAX_COMMAND_CHARS)
    stdin: str = Field(default="", max_length=MAX_STDIN_BYTES)
    timeout_s: float = Field(default=30, gt=0, le=600)


class ExecResult(BaseModel):
    exit_code: int | None = Field(description="None when the command was killed")
    signal: int | None = Field(
        description="Signal that ended it: 9 after a timeout, 24 at the CPU limit"
    )
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    duration_ms: int


class FileRequest(BaseModel):
    op: Literal["list", "read", "write"]
    path: str = Field(default=".", max_length=512)
    content: str | None = Field(default=None, max_length=MAX_FILE_BYTES)


class FileResult(BaseModel):
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
