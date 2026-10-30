import asyncio
import os
from pathlib import Path

import pytest
from pydantic import BaseModel

from seed_api.core.messages import ToolCall
from seed_api.core.tools import Tool, ToolRegistry
from seed_api.core.workspace_tools import workspace_tools

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class In(BaseModel):
    n: int


class Out(BaseModel):
    n: int


def tool(name: str, handler, **kw) -> Tool:  # type: ignore[no-untyped-def]
    return Tool(
        name=name,
        description="d",
        input_model=In,
        output_model=Out,
        handler=handler,
        permission="read",
        **kw,
    )


async def double(i: In) -> Out:
    return Out(n=i.n * 2)


async def hang(i: In) -> Out:
    await asyncio.sleep(5)
    return Out(n=0)


async def boom(i: In) -> Out:
    raise RuntimeError("secret internals")


def call(name: str, **args: object) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=args)


async def test_registry_outcomes() -> None:
    reg = ToolRegistry(
        [
            tool("double", double),
            tool("hang", hang, timeout_s=0.05),
            tool("boom", boom),
            tool("danger", double, requires_approval=True),
        ]
    )
    ok = await reg.execute(call("double", n=4))
    assert ok.ok and ok.output == {"n": 8}
    assert (await reg.execute(call("nope"))).error_kind == "unknown_tool"
    bad = await reg.execute(call("double", n="x"))
    assert bad.error_kind == "invalid_arguments" and "n" in (bad.error or "")
    assert (await reg.execute(call("hang", n=1))).error_kind == "timeout"
    crashed = await reg.execute(call("boom", n=1))
    assert crashed.error_kind == "tool_error" and "secret" not in (crashed.error or "")
    assert (await reg.execute(call("danger", n=1))).error_kind == "approval_required"
    assert (await reg.execute(call("danger", n="x"))).error_kind == "invalid_arguments"


def test_specs_expose_json_schema_and_reject_duplicates() -> None:
    reg = ToolRegistry([tool("double", double)])
    spec = reg.specs()[0]
    assert spec.parameters["properties"]["n"]["type"] == "integer"
    with pytest.raises(ValueError):
        reg.register(tool("double", double))


async def test_workspace_confinement(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    reg = ToolRegistry(workspace_tools(ws))
    (tmp_path / "secret.txt").write_text("top secret")
    os.symlink(tmp_path / "secret.txt", ws / "link.txt")
    for args in ({"path": "../secret.txt"}, {"path": "/etc/passwd"}, {"path": "link.txt"}):
        out = await reg.execute(ToolCall(id="c", name="read_file", arguments=args))
        assert not out.ok and out.error_kind == "tool_error", args
    w = await reg.execute(
        ToolCall(id="c", name="write_file", arguments={"path": "../escape.txt", "content": "x"})
    )
    assert not w.ok and not (tmp_path / "escape.txt").exists()


async def test_workspace_write_list_read(tmp_path: Path) -> None:
    reg = ToolRegistry(workspace_tools(tmp_path))
    await reg.execute(
        ToolCall(
            id="c", name="write_file", arguments={"path": "src/app.html", "content": "<h1>x</h1>"}
        )
    )
    listed = await reg.execute(ToolCall(id="c", name="list_files", arguments={}))
    assert (
        listed.output
        and {"path": "src/app.html", "type": "file", "size": 10} in listed.output["entries"]
    )
    read = await reg.execute(ToolCall(id="c", name="read_file", arguments={"path": "src/app.html"}))
    assert read.output == {"path": "src/app.html", "content": "<h1>x</h1>"}


async def test_listing_says_whether_the_path_is_missing_or_a_file(tmp_path: Path) -> None:
    reg = ToolRegistry(workspace_tools(tmp_path))
    (tmp_path / "a.txt").write_text("x")

    async def listing(path: str) -> str | None:
        out = await reg.execute(ToolCall(id="c", name="list_files", arguments={"path": path}))
        assert not out.ok
        return out.error

    assert await listing("nope") == "No such directory: nope"
    assert await listing("a.txt") == "Not a directory: a.txt is a file."
