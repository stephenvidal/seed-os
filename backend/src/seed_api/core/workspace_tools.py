"""File tools confined to one run's workspace directory.

These are read/write file operations, not command execution: every path is
resolved and must stay inside the workspace (no traversal, no symlink escape).
Shell and other exec tools run only in the isolated sandbox (Milestone 3).
"""

from pathlib import Path

from pydantic import BaseModel, Field

from .tools import Tool, ToolFailure

MAX_FILE_BYTES = 256 * 1024
MAX_LIST_ENTRIES = 500


def _resolve(root: Path, rel: str) -> Path:
    if rel.startswith(("/", "\\")) or "\x00" in rel:
        raise ToolFailure("Paths must be relative to the workspace.")
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise ToolFailure("Path escapes the workspace.")
    return path


class PathInput(BaseModel):
    path: str = Field(default=".", max_length=512, description="Path relative to the workspace")


class ReadInput(BaseModel):
    path: str = Field(max_length=512, description="File path relative to the workspace")


class WriteInput(BaseModel):
    path: str = Field(max_length=512, description="File path relative to the workspace")
    content: str = Field(max_length=MAX_FILE_BYTES, description="Full new file content (UTF-8)")


class Entry(BaseModel):
    path: str
    type: str
    size: int | None = None


class ListOutput(BaseModel):
    entries: list[Entry]
    truncated: bool


class ReadOutput(BaseModel):
    path: str
    content: str


class WriteOutput(BaseModel):
    path: str
    bytes_written: int


def workspace_tools(root: Path) -> list[Tool]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    async def list_files(inp: PathInput) -> ListOutput:
        base = _resolve(root, inp.path)
        if not base.is_dir():
            raise ToolFailure(f"Not a directory: {inp.path}")
        entries: list[Entry] = []
        for p in sorted(base.rglob("*")):
            if len(entries) >= MAX_LIST_ENTRIES:
                return ListOutput(entries=entries, truncated=True)
            rel = str(p.relative_to(root))
            if p.is_symlink():
                entries.append(Entry(path=rel, type="symlink"))
            elif p.is_dir():
                entries.append(Entry(path=rel, type="dir"))
            else:
                entries.append(Entry(path=rel, type="file", size=p.stat().st_size))
        return ListOutput(entries=entries, truncated=False)

    async def read_file(inp: ReadInput) -> ReadOutput:
        path = _resolve(root, inp.path)
        if not path.is_file():
            raise ToolFailure(f"No such file: {inp.path}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ToolFailure("File is larger than the read limit.")
        try:
            return ReadOutput(path=inp.path, content=path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as e:
            raise ToolFailure("File is not UTF-8 text.") from e

    async def write_file(inp: WriteInput) -> WriteOutput:
        path = _resolve(root, inp.path)
        if path == root or path.is_dir():
            raise ToolFailure("Path is a directory.")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = inp.content.encode("utf-8")
        path.write_bytes(data)
        return WriteOutput(path=inp.path, bytes_written=len(data))

    return [
        Tool(
            name="list_files",
            description="List files and directories in the workspace, recursively.",
            input_model=PathInput,
            output_model=ListOutput,
            handler=list_files,
            permission="read",
        ),
        Tool(
            name="read_file",
            description="Read a UTF-8 text file from the workspace.",
            input_model=ReadInput,
            output_model=ReadOutput,
            handler=read_file,
            permission="read",
        ),
        Tool(
            name="write_file",
            description="Create or overwrite a UTF-8 text file in the workspace.",
            input_model=WriteInput,
            output_model=WriteOutput,
            handler=write_file,
            permission="write",
        ),
    ]
