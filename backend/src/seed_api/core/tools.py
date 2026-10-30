"""Typed tool registry. Every tool declares schemas, permissions, and limits.

The registry validates model-supplied arguments against the tool's input model,
enforces the timeout, and turns every failure into a typed outcome the model can
read. A tool that `requires_approval` runs only when the caller says a person
approved this call (the agent loop pauses for that); otherwise it is refused.
Arguments are checked first, so nobody is asked to approve a call that cannot run. A
`deferred` tool never runs in the loop: its result arrives later from outside
the run (a delegated task, D-025), and the loop pauses until it does.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from .messages import ToolCall, ToolSpec

Permission = Literal["read", "write", "network", "exec"]
ToolErrorKind = Literal[
    "unknown_tool", "invalid_arguments", "timeout", "approval_required", "denied", "tool_error"
]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[BaseModel]]
    permission: Permission
    timeout_s: float = 10.0
    requires_approval: bool = False
    deferred: bool = False
    max_output_chars: int = 20_000

    def spec(self) -> ToolSpec:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, parameters=schema)


class ToolOutcome(BaseModel):
    call_id: str
    tool: str
    ok: bool
    output: dict[str, Any] | None = None
    error_kind: ToolErrorKind | None = None
    error: str | None = None
    duration_ms: int = 0

    def as_model_content(self) -> str:
        """What the model sees: the output, or a short typed error it can react to."""
        if self.ok:
            return json.dumps(self.output, ensure_ascii=False)
        return json.dumps({"error": self.error_kind, "message": self.error})


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    async def execute(self, call: ToolCall, *, approved: bool = False) -> ToolOutcome:
        started = time.monotonic()

        def done(**kw: Any) -> ToolOutcome:
            ms = int((time.monotonic() - started) * 1000)
            return ToolOutcome(call_id=call.id, tool=call.name, duration_ms=ms, **kw)

        tool = self._tools.get(call.name)
        if tool is None:
            return done(ok=False, error_kind="unknown_tool", error=f"No tool named {call.name!r}.")
        try:
            args = tool.input_model.model_validate(call.arguments)
        except ValidationError as e:
            fields = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
            return done(ok=False, error_kind="invalid_arguments", error=fields[:500])
        if tool.requires_approval and not approved:
            return done(
                ok=False,
                error_kind="approval_required",
                error="This tool needs a person's approval, which this call does not have.",
            )
        try:
            result = await asyncio.wait_for(tool.handler(args), timeout=tool.timeout_s)
        except TimeoutError:
            return done(ok=False, error_kind="timeout", error=f"Exceeded {tool.timeout_s}s.")
        except ToolFailure as e:
            return done(ok=False, error_kind="tool_error", error=str(e)[:500])
        except Exception as e:  # noqa: BLE001 - a tool bug must not kill the run; it is reported
            return done(
                ok=False, error_kind="tool_error", error=f"Internal tool error: {type(e).__name__}"
            )
        output = tool.output_model.model_validate(result).model_dump(mode="json")
        if len(json.dumps(output)) > tool.max_output_chars:
            return done(ok=False, error_kind="tool_error", error="Output exceeded the size limit.")
        return done(ok=True, output=output)


class ToolFailure(Exception):
    """Raised by a tool handler for an expected, reportable failure."""
