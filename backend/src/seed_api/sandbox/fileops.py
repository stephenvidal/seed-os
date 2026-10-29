"""File operations inside a task's workspace, run by the sandbox as the task's user.

Reads one FileRequest as JSON on stdin and writes one FileResult as JSON on
stdout. The working directory is the workspace. Running as the task's own user
means the kernel, not only path checks, keeps it out of other workspaces.
"""

import base64
import binascii
import sys
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ..core.tools import ToolFailure
from ..core.workspace_tools import list_entries, read_text, write_text
from ..studio.files import read_bytes, snapshot, write_bytes
from .protocol import FileRequest, FileResult


def handle(req: FileRequest, root: Path) -> FileResult:
    out: BaseModel
    try:
        if req.op == "list":
            out = list_entries(root, req.path)
        elif req.op == "read":
            out = read_text(root, req.path)
        elif req.op == "snapshot":
            out = snapshot(root)
        elif req.op == "read_bytes":
            data = base64.b64encode(read_bytes(root, req.path)).decode()
            return FileResult(ok=True, result={"path": req.path, "data": data})
        elif req.op == "write_bytes":
            if req.data is None:
                return FileResult(ok=False, error="Write needs data.")
            try:
                raw = base64.b64decode(req.data, validate=True)
            except binascii.Error:
                return FileResult(ok=False, error="Data is not base64.")
            write_bytes(root, req.path, raw)
            return FileResult(ok=True, result={"path": req.path, "bytes_written": len(raw)})
        else:
            if req.content is None:
                return FileResult(ok=False, error="Write needs content.")
            out = write_text(root, req.path, req.content)
    except ToolFailure as e:
        return FileResult(ok=False, error=str(e))
    except OSError as e:
        return FileResult(ok=False, error=f"{e.strerror or type(e).__name__}: {req.path}")
    return FileResult(ok=True, result=out.model_dump())


def main() -> int:
    try:
        req = FileRequest.model_validate_json(sys.stdin.read())
    except ValidationError as e:
        print(
            FileResult(
                ok=False, error=f"Invalid request: {e.error_count()} error(s)"
            ).model_dump_json()
        )
        return 0
    print(handle(req, Path.cwd().resolve()).model_dump_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
