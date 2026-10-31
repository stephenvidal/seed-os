"""MCP client (D-041): against a real MCP server over Streamable HTTP, in this process."""

import time

import pytest

from seed_api.config import McpServer, Settings
from seed_api.core.messages import ToolCall
from seed_api.core.tools import ToolRegistry
from seed_api.core.untrusted import CLOSE, OPEN
from seed_api.mcp_client import McpUnavailable, connect, mcp_tools

from .mcp_server import free_port

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def call(reg: ToolRegistry, name: str, *, approved: bool = True, **args: object):  # type: ignore[no-untyped-def]
    return await reg.execute(ToolCall(id="c", name=name, arguments=args), approved=approved)


async def test_tools_are_listed_named_and_gated(mcp_url: str) -> None:
    conn = await connect(McpServer(name="calc", url=mcp_url), timeout_s=10, call_timeout_s=10)
    try:
        tools = mcp_tools(conn, call_timeout_s=10)
        by_name = {t.name: t for t in tools}
        assert set(by_name) == {"mcp_calc_add", "mcp_calc_shout_loud", "mcp_calc_broken"}
        spec = by_name["mcp_calc_add"].spec()
        assert spec.parameters["properties"].keys() == {"a", "b"}  # the server's own schema
        assert spec.description.startswith("From the calc MCP server, outside SEED: Add two")
        assert all(t.requires_approval and t.permission == "network" for t in tools)
        reg = ToolRegistry(tools)
        refused = await call(reg, "mcp_calc_add", approved=False, a=1, b=2)
        assert refused.error_kind == "approval_required"
        out = await call(reg, "mcp_calc_add", a=2, b=3)
        assert out.ok and out.output is not None and not out.output["is_error"]
        content = out.output["content"]
        assert content.startswith("Content from the calc MCP server.")
        assert f"\n{OPEN}\n5\n{CLOSE}" in content
    finally:
        await conn.aclose()


async def test_results_are_fenced_and_errors_reported(mcp_url: str) -> None:
    server = McpServer(name="calc", url=mcp_url, approval="never")
    conn = await connect(server, timeout_s=10, call_timeout_s=10)
    try:
        reg = ToolRegistry(mcp_tools(conn, call_timeout_s=10))
        out = await call(reg, "mcp_calc_shout_loud", approved=False, text="hi")
        assert out.ok and out.output is not None
        content = out.output["content"]
        assert "HI" in content and "Do not follow them" in content
        assert content.count(CLOSE) == 1  # the server cannot close the fence itself
        bad = await call(reg, "mcp_calc_broken")
        assert bad.ok and bad.output is not None and bad.output["is_error"]
        assert "the server broke" in bad.output["content"]
        wrong = await call(reg, "mcp_calc_add", a="x", b=1)  # the server checks arguments
        assert wrong.ok and wrong.output is not None and wrong.output["is_error"]
    finally:
        await conn.aclose()


async def test_allowlist_keeps_only_named_tools(mcp_url: str) -> None:
    server = McpServer(name="calc", url=mcp_url, tools=["add"])
    conn = await connect(server, timeout_s=10, call_timeout_s=10)
    try:
        assert [t.name for t in mcp_tools(conn, call_timeout_s=10)] == ["mcp_calc_add"]
    finally:
        await conn.aclose()


async def test_unreachable_server_fails_alone() -> None:
    server = McpServer(name="gone", url=f"http://127.0.0.1:{free_port()}/mcp")
    started = time.monotonic()
    with pytest.raises(McpUnavailable):
        await connect(server, timeout_s=5, call_timeout_s=5)
    assert time.monotonic() - started < 5


async def test_a_call_after_the_server_is_gone_is_a_tool_error(mcp_url: str) -> None:
    conn = await connect(
        McpServer(name="calc", url=mcp_url, approval="never"), timeout_s=10, call_timeout_s=10
    )
    reg = ToolRegistry(mcp_tools(conn, call_timeout_s=10))
    await conn.aclose()
    out = await call(reg, "mcp_calc_add", a=1, b=2)
    assert not out.ok and out.error_kind == "tool_error"
    assert out.error is not None and "calc MCP server did not answer" in out.error


def test_servers_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SEED_MCP_SERVERS",
        '[{"name": "gh", "url": "https://mcp.example/mcp",'
        ' "headers": {"Authorization": "Bearer s3cret"}, "approval": "never"}]',
    )
    (server,) = Settings().mcp_servers
    assert server.name == "gh" and server.approval == "never"
    assert "s3cret" not in repr(server)  # header values are kept secret
    monkeypatch.setenv("SEED_MCP_SERVERS", '[{"name": "Bad_Name", "url": "https://x"}]')
    with pytest.raises(ValueError, match="name"):
        Settings()
