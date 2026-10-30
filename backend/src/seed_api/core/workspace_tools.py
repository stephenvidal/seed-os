"""File tools confined to one run's workspace directory.

These are read/write file operations, not command execution: every path is
resolved and must stay inside the workspace (no traversal, no symlink escape).
Shell commands run only in the isolated sandbox (`seed_api.sandbox`), which
uses the same file operations, run there as the task's own user.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from .tools import Tool, ToolFailure

MAX_FILE_BYTES = 256 * 1024
MAX_LIST_ENTRIES = 500


def resolve(root: Path, rel: str) -> Path:
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


def list_entries(root: Path, rel: str) -> ListOutput:
    base = resolve(root, rel)
    if not base.exists():
        raise ToolFailure(f"No such directory: {rel}")
    if not base.is_dir():
        raise ToolFailure(f"Not a directory: {rel} is a file.")
    entries: list[Entry] = []
    for p in sorted(base.rglob("*")):
        if len(entries) >= MAX_LIST_ENTRIES:
            return ListOutput(entries=entries, truncated=True)
        path = str(p.relative_to(root))
        if p.is_symlink():
            entries.append(Entry(path=path, type="symlink"))
        elif p.is_dir():
            entries.append(Entry(path=path, type="dir"))
        else:
            entries.append(Entry(path=path, type="file", size=p.stat().st_size))
    return ListOutput(entries=entries, truncated=False)


def read_text(root: Path, rel: str) -> ReadOutput:
    path = resolve(root, rel)
    if not path.is_file():
        raise ToolFailure(f"No such file: {rel}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ToolFailure("File is larger than the read limit.")
    try:
        return ReadOutput(path=rel, content=path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as e:
        raise ToolFailure("File is not UTF-8 text.") from e


def write_text(root: Path, rel: str, content: str) -> WriteOutput:
    path = resolve(root, rel)
    if path == root or path.is_dir():
        raise ToolFailure("Path is a directory.")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    path.write_bytes(data)
    return WriteOutput(path=rel, bytes_written=len(data))


LIST_DESCRIPTION = "List files and directories in the workspace, recursively."
READ_DESCRIPTION = "Read a UTF-8 text file from the workspace."
WRITE_DESCRIPTION = "Create or overwrite a UTF-8 text file in the workspace."


def workspace_tools(root: Path) -> list[Tool]:
    """File tools on a local directory (the worker, when no sandbox is configured)."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    async def list_files(inp: PathInput) -> ListOutput:
        return list_entries(root, inp.path)

    async def read_file(inp: ReadInput) -> ReadOutput:
        return read_text(root, inp.path)

    async def write_file(inp: WriteInput) -> WriteOutput:
        return write_text(root, inp.path, inp.content)

    return [
        Tool(
            name="list_files",
            description=LIST_DESCRIPTION,
            input_model=PathInput,
            output_model=ListOutput,
            handler=list_files,
            permission="read",
        ),
        Tool(
            name="read_file",
            description=READ_DESCRIPTION,
            input_model=ReadInput,
            output_model=ReadOutput,
            handler=read_file,
            permission="read",
        ),
        Tool(
            name="write_file",
            description=WRITE_DESCRIPTION,
            input_model=WriteInput,
            output_model=WriteOutput,
            handler=write_file,
            permission="write",
        ),
    ]
