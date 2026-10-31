"""Remote MCP servers as tools for SEED's own runs (D-041).

A run connects to each configured server over Streamable HTTP, lists its tools and
offers them to the model as `mcp_<server>_<tool>`. Every call waits for the owner's
approval unless the server is configured otherwise, and whatever comes back is
fenced as untrusted content: SEED did not write it.

Each connection lives in a task of its own, opened and closed there, so a server
that cannot be reached, or drops mid-run, fails alone: its tools are missing or
report an error, and the run goes on.
"""

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents
from mcp.types import Tool as McpTool
from pydantic import BaseModel, ConfigDict

from .config import McpServer
from .core.tools import Tool, ToolFailure
from .core.untrusted import untrusted

log = logging.getLogger(__name__)

NAME_LIMIT = 64  # the longest tool name model providers accept
DESCRIPTION_CHARS = 1_000
RESULT_CHARS = 12_000
LIST_PAGES = 5


class McpArguments(BaseModel):
    """Whatever the model sends; the server checks it against its own schema."""

    model_config = ConfigDict(extra="allow")


class McpOutput(BaseModel):
    content: str
    is_error: bool = False


class McpUnavailable(Exception):
    """A server could not be connected to; the reason is safe to show the owner."""


@dataclass
class McpConnection:
    server: McpServer
    session: ClientSession
    tools: list[McpTool]
    _stop: asyncio.Event
    _task: "asyncio.Task[None]"

    async def aclose(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout_s)
        except TimeoutError:
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task


def _reason(e: BaseException) -> str:
    if isinstance(e, BaseExceptionGroup):
        inner = [x for x in e.exceptions if not isinstance(x, asyncio.CancelledError)]
        if inner:
            return _reason(inner[0])
    if isinstance(e, asyncio.CancelledError):
        return "the connection was closed"
    return type(e).__name__


async def connect(server: McpServer, *, timeout_s: float, call_timeout_s: float) -> McpConnection:
    """Open a session with one server and list its tools, or raise McpUnavailable."""
    ready: asyncio.Future[tuple[ClientSession, list[McpTool]]] = (
        asyncio.get_running_loop().create_future()
    )
    stop = asyncio.Event()
    headers = {k: v.get_secret_value() for k, v in server.headers.items()}

    async def hold() -> None:
        try:
            async with (
                httpx.AsyncClient(
                    headers=headers, timeout=httpx.Timeout(timeout_s, read=call_timeout_s)
                ) as http,
                streamable_http_client(server.url, http_client=http) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                tools: list[McpTool] = []
                cursor: str | None = None
                for _ in range(LIST_PAGES):
                    page = await session.list_tools(cursor=cursor)
                    tools.extend(page.tools)
                    cursor = page.nextCursor
                    if not cursor:
                        break
                ready.set_result((session, tools))
                await stop.wait()
        except BaseException as e:  # noqa: BLE001 - this task owns the connection; it ends here
            if not ready.done():
                ready.set_exception(McpUnavailable(_reason(e)))
            elif not stop.is_set():
                log.warning("MCP server %s dropped: %s", server.name, _reason(e))

    task = asyncio.create_task(hold(), name=f"mcp:{server.name}")
    try:
        session, tools = await asyncio.wait_for(asyncio.shield(ready), timeout_s)
    except BaseException as e:
        ready.cancel()  # nobody waits for it now; hold() must not set it
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        if isinstance(e, TimeoutError):
            raise McpUnavailable(f"no answer within {timeout_s:g}s") from None
        raise
    return McpConnection(server, session, tools, stop, task)


def _tool_name(server: str, tool: str) -> str:
    return f"mcp_{server}_{re.sub(r'[^A-Za-z0-9_-]', '_', tool)}"[:NAME_LIMIT]


def _text(result: CallToolResult) -> str:
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, EmbeddedResource) and isinstance(
            block.resource, TextResourceContents
        ):
            parts.append(block.resource.text)
        else:
            parts.append(f"[{block.type} content left out]")
    if not any(isinstance(b, TextContent) for b in result.content) and result.structuredContent:
        parts.append(json.dumps(result.structuredContent, ensure_ascii=False))
    return "\n\n".join(parts) or "(no content)"


def mcp_tools(connection: McpConnection, *, call_timeout_s: float) -> list[Tool]:
    """The server's tools as SEED tools, minus any the owner left out of its list."""
    server = connection.server
    wanted = set(server.tools) if server.tools is not None else None
    out: list[Tool] = []
    names: set[str] = set()
    for spec in connection.tools:
        if wanted is not None and spec.name not in wanted:
            continue
        name = _tool_name(server.name, spec.name)
        if name in names:  # two names that read the same once made safe; keep the first
            log.warning("MCP server %s: tool %r skipped, name taken", server.name, spec.name)
            continue
        names.add(name)
        out.append(_tool(connection, spec, name, call_timeout_s))
    return out


def _tool(connection: McpConnection, spec: McpTool, name: str, call_timeout_s: float) -> Tool:
    server = connection.server
    remote = spec.name

    async def handler(args: McpArguments) -> McpOutput:
        try:
            result = await connection.session.call_tool(remote, args.model_dump())
        except Exception as e:  # noqa: BLE001 - any transport failure is the server's, reported
            raise ToolFailure(
                f"The {server.name} MCP server did not answer ({type(e).__name__})."
            ) from e
        text = untrusted(f"the {server.name} MCP server", _text(result), limit=RESULT_CHARS)
        return McpOutput(content=text, is_error=result.isError)

    schema: dict[str, Any] = dict(spec.inputSchema or {"type": "object"})
    description = (spec.description or spec.title or remote).strip()[:DESCRIPTION_CHARS]
    return Tool(
        name=name,
        description=f"From the {server.name} MCP server, outside SEED: {description}",
        input_model=McpArguments,
        output_model=McpOutput,
        handler=handler,
        permission="network",
        timeout_s=call_timeout_s,
        requires_approval=server.approval == "always",
        max_output_chars=RESULT_CHARS + 2_000,
        parameters=schema,
    )
