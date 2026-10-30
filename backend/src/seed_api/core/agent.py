"""The bounded agent loop: model → tool calls → observations → model, until done.

Every run terminates for an explicit, recorded reason. Limits cap steps, wall
time, tokens, and tool calls per step; retryable provider errors are retried a
bounded number of times; cancellation is checked between every unit of work.
Events are emitted in order with a sequence number so they can be persisted and
replayed. After each step whose tool results are all recorded, the loop offers a
checkpoint; a run resumed from one continues at the next step instead of redoing
finished work (SEED Flow).

A tool that requires approval is not run until a person decides. The run pauses
on it (termination `awaiting_approval`) after checkpointing the step's calls that
have not run yet; resumed with that person's decisions, it runs them in order
(a denied call's result tells the model so) and carries on.

A deferred tool (delegation, D-025) pauses the run the same way (termination
`awaiting_delegation`); resumed with the call's result in `delegated`, the loop
records that result as the call's and carries on.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .messages import ChatRequest, ChatResult, Completed, Message, TextDelta, ToolCall, Usage
from .pricing import ModelPrice
from .providers.base import Provider, ProviderError
from .tools import Tool, ToolOutcome, ToolRegistry

Termination = Literal[
    "completed",
    "max_steps",
    "deadline",
    "token_budget",
    "cost_budget",
    "provider_error",
    "cancelled",
    "awaiting_approval",
    "awaiting_delegation",
]


class RunLimits(BaseModel):
    max_steps: int = Field(default=8, ge=1, le=100)
    max_runtime_s: float = Field(default=300, gt=0, le=3600)
    max_total_tokens: int = Field(default=200_000, ge=1)
    # A dollar cap on the run, with the price that turns its tokens into dollars.
    max_cost_usd: float | None = Field(default=None, gt=0)
    price: ModelPrice | None = None
    max_tool_calls_per_step: int = Field(default=8, ge=1, le=64)
    max_output_tokens_per_step: int | None = Field(default=16_384, gt=0)
    provider_retries: int = Field(default=2, ge=0, le=5)


EventType = Literal[
    "run_started",
    "step_started",
    "text_delta",
    "tool_call",
    "tool_result",
    "step_completed",
    "provider_retry",
    "approval_requested",
    "delegation_requested",
    "run_finished",
]


class RunEvent(BaseModel):
    seq: int
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    termination: Termination
    final_text: str
    steps: int
    usage: Usage
    messages: list[Message]
    error: str | None = None
    # Set when termination is awaiting_approval or awaiting_delegation: the call
    # that waits for a person or for a delegated task.
    awaiting: ToolCall | None = None


class Checkpoint(BaseModel):
    """A resume-safe point: every tool call the model asked for has a recorded
    result, except `pending`: the last step's calls not run yet because the first
    of them waits for approval or for a delegated task."""

    messages: list[Message]
    steps: int
    usage: Usage
    pending: list[ToolCall] = Field(default_factory=list)


DENIED = "The user denied this action. Do not try it again; continue without it."

WRAP_UP = (
    "You have reached the step limit for this request and can no longer use tools. "
    "Reply now with your final answer, using what you already have. If the work is "
    "unfinished, say what is done and what is left."
)


class DelegatedResult(BaseModel):
    """What a delegated call came back with (D-025)."""

    ok: bool
    content: str


EventSink = Callable[[RunEvent], Awaitable[None]]
CheckpointSink = Callable[[Checkpoint], Awaitable[None]]


def _valid(tool: Tool, call: ToolCall) -> bool:
    """Whether the call's arguments fit the tool. A deferred call that does not is
    run like any other, so the registry reports the invalid arguments."""
    try:
        tool.input_model.model_validate(call.arguments)
    except ValidationError:
        return False
    return True


class _Emitter:
    def __init__(self, sink: EventSink) -> None:
        self._sink = sink
        self._seq = 0

    async def __call__(self, type_: EventType, **data: Any) -> None:
        self._seq += 1
        await self._sink(RunEvent(seq=self._seq, type=type_, data=data))


async def run_agent(
    *,
    provider: Provider,
    model: str,
    messages: list[Message],
    tools: ToolRegistry,
    limits: RunLimits,
    on_event: EventSink,
    cancel: asyncio.Event | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_checkpoint: CheckpointSink | None = None,
    resume: Checkpoint | None = None,
    approvals: Mapping[str, bool] | None = None,
    delegated: Mapping[str, DelegatedResult] | None = None,
) -> RunResult:
    """Run the loop. With `resume`, `messages` is ignored and the run continues from
    the checkpoint; the step and token limits count across the whole run.
    `approvals` maps tool call ids to a person's decision (True = approved);
    `delegated` maps deferred calls' ids to the results that came back."""
    emit = _Emitter(on_event)
    cancel = cancel or asyncio.Event()
    history = list(resume.messages if resume else messages)
    usage = resume.usage if resume else Usage()
    deadline = time.monotonic() + limits.max_runtime_s
    specs = tools.specs()
    steps = resume.steps if resume else 0
    final_text = ""

    async def finish(
        term: Termination, error: str | None = None, awaiting: ToolCall | None = None
    ) -> RunResult:
        await emit(
            "run_finished",
            termination=term,
            steps=steps,
            usage=usage.model_dump(),
            error=error,
        )
        return RunResult(
            termination=term,
            final_text=final_text,
            steps=steps,
            usage=usage,
            messages=history,
            error=error,
            awaiting=awaiting,
        )

    async def run_calls(
        calls: list[ToolCall], offset: int, announced: str | None
    ) -> tuple[int, Termination] | None:
        """Run one step's calls in order (`offset` = index of calls[0] in the step).
        Returns the index in `calls` of the first that waits for approval or for a
        delegated task, and which, having run none from it on; None once all have
        results. `announced` is a call whose tool_call event was already emitted
        before a pause."""
        decided = approvals or {}
        returned = delegated or {}
        for i, call in enumerate(calls):
            if cancel.is_set():
                raise _Cancelled
            if call.id != announced:
                await emit(
                    "tool_call", step=steps, id=call.id, name=call.name, arguments=call.arguments
                )
            tool = tools.get(call.name)
            within_cap = offset + i < limits.max_tool_calls_per_step
            # A call whose arguments do not fit is answered at once, not put to a person.
            needs = (
                within_cap and tool is not None and tool.requires_approval and _valid(tool, call)
            )
            if needs and call.id not in decided:
                await emit(
                    "approval_requested",
                    step=steps,
                    id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                )
                return i, "awaiting_approval"
            deferred = within_cap and tool is not None and tool.deferred
            if deferred and call.id in returned:
                back = returned[call.id]
                outcome_content = back.content
                await emit(
                    "tool_result",
                    step=steps,
                    id=call.id,
                    tool=call.name,
                    ok=back.ok,
                    **({} if back.ok else {"error": "The delegated task did not complete."}),
                )
            elif deferred and tool is not None and _valid(tool, call):
                await emit(
                    "delegation_requested",
                    step=steps,
                    id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                )
                return i, "awaiting_delegation"
            elif not within_cap:
                outcome_content = (
                    '{"error": "limit", "message": "Too many tool calls in one step; skipped."}'
                )
                await emit("tool_result", step=steps, id=call.id, ok=False, error_kind="limit")
            else:
                if needs and not decided[call.id]:
                    outcome = ToolOutcome(
                        call_id=call.id, tool=call.name, ok=False, error_kind="denied", error=DENIED
                    )
                else:
                    outcome = await tools.execute(call, approved=needs)
                outcome_content = outcome.as_model_content()
                await emit(
                    "tool_result", step=steps, **outcome.model_dump(exclude={"call_id"}), id=call.id
                )
            history.append(
                Message(
                    role="tool", content=outcome_content, tool_call_id=call.id, tool_name=call.name
                )
            )
        return None

    async def settle_step(
        calls: list[ToolCall], offset: int, announced: str | None
    ) -> RunResult | None:
        """Run calls and checkpoint. Returns a result when the run must stop."""
        try:
            waiting = await run_calls(calls, offset, announced)
        except _Cancelled:
            return await finish("cancelled")
        pending = [] if waiting is None else calls[waiting[0] :]
        if on_checkpoint is not None:
            await on_checkpoint(
                Checkpoint(messages=history, steps=steps, usage=usage, pending=pending)
            )
        if waiting is not None:
            return await finish(waiting[1], awaiting=calls[waiting[0]])
        return None

    await emit(
        "run_started",
        model=model,
        provider=provider.name,
        limits=limits.model_dump(),
        resumed_at_step=steps if resume else None,
    )

    if resume and resume.pending:
        # Resuming after a pause for approval: finish that step's remaining calls.
        step_calls = next(m for m in reversed(history) if m.role == "assistant").tool_calls
        offset = [c.id for c in step_calls].index(resume.pending[0].id)
        stopped = await settle_step(resume.pending, offset, announced=resume.pending[0].id)
        if stopped is not None:
            return stopped

    while True:
        if cancel.is_set():
            return await finish("cancelled")
        if steps >= limits.max_steps:
            return await finish("max_steps")
        if time.monotonic() >= deadline:
            return await finish("deadline")
        if usage.input_tokens + usage.output_tokens >= limits.max_total_tokens:
            return await finish("token_budget")
        if (
            limits.max_cost_usd is not None
            and limits.price is not None
            and limits.price.cost(usage) >= limits.max_cost_usd
        ):
            return await finish("cost_budget")

        steps += 1
        # The last allowed step gets no tools and is told to answer, so a run that
        # spent its steps on tool calls still ends with an answer, not nothing.
        wrap_up = limits.max_steps > 1 and steps == limits.max_steps
        await emit("step_started", step=steps, **({"wrap_up": True} if wrap_up else {}))
        request = ChatRequest(
            model=model,
            messages=[*history, Message(role="system", content=WRAP_UP)] if wrap_up else history,
            tools=[] if wrap_up else specs,
            max_output_tokens=limits.max_output_tokens_per_step,
        )

        result: ChatResult | None = None
        attempt = 0
        while result is None:
            try:
                result = await asyncio.wait_for(
                    _until_cancelled(_stream_step(provider, request, emit, cancel), cancel),
                    timeout=max(0.001, deadline - time.monotonic()),
                )
            except TimeoutError:
                return await finish("deadline")
            except ProviderError as e:
                if e.retryable and attempt < limits.provider_retries and not cancel.is_set():
                    attempt += 1
                    delay = min(8.0, 0.5 * 2**attempt)
                    await emit("provider_retry", attempt=attempt, kind=e.kind, delay_s=delay)
                    await sleep(delay)
                    continue
                return await finish("provider_error", error=f"{e.kind}: {e.message}")
            except _Cancelled:
                return await finish("cancelled")

        usage = usage + result.usage
        history.append(result.message)
        final_text = result.message.content
        calls = result.message.tool_calls
        await emit(
            "step_completed",
            step=steps,
            finish_reason=result.finish_reason,
            usage=result.usage.model_dump(),
            latency_ms=result.latency_ms,
            tool_calls=len(calls),
        )
        if not calls:
            return await finish("completed")
        if wrap_up:  # tools were withheld; a model that still asks for them gets none
            return await finish("max_steps")

        stopped = await settle_step(calls, 0, announced=None)
        if stopped is not None:
            return stopped


class _Cancelled(Exception):
    pass


async def _until_cancelled(step: Awaitable[ChatResult], cancel: asyncio.Event) -> ChatResult:
    """Await one provider step, abandoning it as soon as `cancel` is set, even while
    the provider is blocked mid-request."""
    task = asyncio.ensure_future(step)
    waiter = asyncio.ensure_future(cancel.wait())
    try:
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
        if not task.done():
            task.cancel()
    if task.done() and not task.cancelled():
        return task.result()
    raise _Cancelled


async def _stream_step(
    provider: Provider,
    request: ChatRequest,
    emit: _Emitter,
    cancel: asyncio.Event,
) -> ChatResult:
    async for event in provider.stream(request):
        if cancel.is_set():
            raise _Cancelled
        if isinstance(event, TextDelta):
            await emit("text_delta", text=event.text)
        elif isinstance(event, Completed):
            return event.result
    raise ProviderError(provider.name, "bad_response", "stream ended without a result")
