"""Tools API (D-028): the tools SEED can use, under which permissions and limits, and
how they have been used, for the Tools & Skills page.

The catalog is built from the same tool definitions the worker registers, so it
cannot drift from them. Their handlers are never called here: they are built
with no stores or sandbox behind them, only to read what each tool declares.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from pydantic import BaseModel

from .agents.delegation import delegate_tool
from .auth import Principal, require_role
from .config import Settings, get_settings
from .core.tools import Permission, Tool
from .flow.store import TaskStore
from .projects.knowledge import knowledge_tool
from .projects.memory import remember_tool
from .sandbox.client import sandbox_tools

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])
AdminOnly = Annotated[Principal, Depends(require_role("admin"))]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# Where each tool is offered. Fixed by the worker's code (flow/worker.py).
AVAILABLE_IN: dict[str, str] = {
    "list_files": "Every task and chat turn",
    "read_file": "Every task and chat turn",
    "write_file": "Every task and chat turn",
    "run_command": "Tasks run by a worker with a sandbox (SEED_SANDBOX_URL)",
    "search_knowledge": "Tasks and chats in a project",
    "remember": "Chats in a project; proposes a note you approve",
    "delegate": "Tasks that may hand work on (SEED_DELEGATION_MAX_DEPTH), once you have agents",
}


class Argument(BaseModel):
    name: str
    type: str
    required: bool
    description: str


class ToolInfo(BaseModel):
    name: str
    description: str
    permission: Permission
    timeout_s: float
    max_output_chars: int
    # A person approves each call first: the tool asks for it, or SEED_APPROVAL_REQUIRED_TOOLS
    # names it.
    requires_approval: bool
    # Its result comes from another task, not from running here (delegation).
    deferred: bool
    available_in: str
    arguments: list[Argument]


class ToolUsage(BaseModel):
    tool: str
    calls: int
    ok: int
    failed: int
    avg_ms: int | None
    # Failures by kind (denied, timeout, invalid_arguments, tool_error, ...).
    failures: dict[str, int]


class ToolsView(BaseModel):
    generated_at: datetime | None
    window_hours: int
    tools: list[ToolInfo]
    # None when no database is configured: nothing has been recorded.
    usage: list[ToolUsage] | None


def _arguments(tool: Tool) -> list[Argument]:
    schema = tool.input_model.model_json_schema()
    required = set(schema.get("required", []))
    out: list[Argument] = []
    for name, prop in schema.get("properties", {}).items():
        kind = prop.get("type") or "/".join(
            str(p.get("type")) for p in prop.get("anyOf", []) if p.get("type") != "null"
        )
        out.append(
            Argument(
                name=name,
                type=str(kind or "any"),
                required=name in required,
                description=str(prop.get("description", "")),
            )
        )
    return out


def catalog(settings: Settings) -> list[ToolInfo]:
    """Every tool the worker can offer, with the approval policy in force."""
    none: Any = None  # stands in for a store or client; handlers are never called
    nil = uuid.UUID(int=0)
    # The file tools are the same three whether they run in the sandbox or on local
    # disk (workspace_tools), so the sandbox's definitions stand for both.
    tools: list[Tool] = [
        *sandbox_tools(none, nil, settings.sandbox_command_timeout_seconds),
        remember_tool(none, project_id=nil, task_id=nil, conversation_id=None),
        knowledge_tool(none, project_id=nil),
        delegate_tool([]),
    ]
    gated = set(settings.approval_required_tools)
    out: list[ToolInfo] = []
    for t in tools:
        # The delegate tool lists its owner's agents; with none to list, drop the stub.
        text = (
            t.description.rstrip().removesuffix("Agents:").rstrip() if t.deferred else t.description
        )
        out.append(
            ToolInfo(
                name=t.name,
                description=text,
                permission=t.permission,
                timeout_s=t.timeout_s,
                max_output_chars=t.max_output_chars,
                requires_approval=t.requires_approval or t.name in gated,
                deferred=t.deferred,
                available_in=AVAILABLE_IN[t.name],
                arguments=_arguments(t),
            )
        )
    return out


async def usage(conn: AsyncConnection[DictRow], since: datetime) -> list[ToolUsage]:
    """Tool results recorded since `since`, by tool, most used first."""
    cur = await conn.execute(
        """
        SELECT data->>'tool' AS tool, count(*)::int AS calls,
               count(*) FILTER (WHERE data->>'ok' = 'true')::int AS ok,
               avg((data->>'duration_ms')::numeric)::int AS avg_ms
        FROM task_events
        WHERE type = 'tool_result' AND created_at >= %(since)s AND data ? 'tool'
        GROUP BY 1 ORDER BY calls DESC, tool
        """,
        {"since": since},
    )
    rows = await cur.fetchall()
    cur = await conn.execute(
        """
        SELECT data->>'tool' AS tool, coalesce(data->>'error_kind', 'tool_error') AS kind,
               count(*)::int AS n
        FROM task_events
        WHERE type = 'tool_result' AND created_at >= %(since)s AND data ? 'tool'
          AND data->>'ok' <> 'true'
        GROUP BY 1, 2
        """,
        {"since": since},
    )
    failures: dict[str, dict[str, int]] = {}
    for r in await cur.fetchall():
        failures.setdefault(r["tool"], {})[r["kind"]] = r["n"]
    return [
        ToolUsage(
            tool=r["tool"],
            calls=r["calls"],
            ok=r["ok"],
            failed=r["calls"] - r["ok"],
            avg_ms=r["avg_ms"],
            failures=failures.get(r["tool"], {}),
        )
        for r in rows
    ]


@router.get("", response_model=ToolsView)
async def tools(
    request: Request,
    _: AdminOnly,
    settings: SettingsDep,
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> ToolsView:
    """The tool catalog, and tool use over the last `hours` when tasks are stored."""
    store: TaskStore | None = getattr(request.app.state, "task_store", None)
    if store is None:
        return ToolsView(generated_at=None, window_hours=hours, tools=catalog(settings), usage=None)
    async with store.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT now() AS at, now() - make_interval(hours => %s) AS since", (hours,)
        )
        clock = await cur.fetchone()
        assert clock is not None  # noqa: S101 - a SELECT without FROM yields one row
        used = await usage(conn, clock["since"])
    return ToolsView(
        generated_at=clock["at"], window_hours=hours, tools=catalog(settings), usage=used
    )
