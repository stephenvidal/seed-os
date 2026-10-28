"""The bounded agent loop: model → tool calls → observations → model, until done.

Every run terminates for an explicit, recorded reason. Limits cap steps, wall
time, tokens, and tool calls per step; retryable provider errors are retried a
bounded number of times; cancellation is checked between every unit of work.
Events are emitted in order with a sequence number so they can be persisted and
replayed. After each step whose tool results are all recorded, the loop offers a
checkpoint; a run resumed from one continues at the next step instead of redoing
finished work (SEED Flow).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from .messages import ChatRequest, ChatResult, Completed, Message, TextDelta, Usage
from .providers.base import Provider, ProviderError
from .tools import ToolRegistry

Termination = Literal[
    "completed", "max_steps", "deadline", "token_budget", "provider_error", "cancelled"
]


class RunLimits(BaseModel):
    max_steps: int = Field(default=8, ge=1, le=100)
    max_runtime_s: float = Field(default=300, gt=0, le=3600)
    max_total_tokens: int = Field(default=200_000, ge=1)
    max_tool_calls_per_step: int = Field(default=8, ge=1, le=64)
    max_output_tokens_per_step: int | None = Field(default=4096, gt=0)
    provider_retries: int = Field(default=2, ge=0, le=5)


EventType = Literal[
    "run_started",
    "step_started",
    "text_delta",
    "tool_call",
    "tool_result",
    "step_completed",
    "provider_retry",
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


class Checkpoint(BaseModel):
    """A resume-safe point: every tool call the model asked for has a recorded result."""

    messages: list[Message]
    steps: int
    usage: Usage


EventSink = Callable[[RunEvent], Awaitable[None]]
CheckpointSink = Callable[[Checkpoint], Awaitable[None]]


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
) -> RunResult:
    """Run the loop. With `resume`, `messages` is ignored and the run continues from
    the checkpoint; the step and token limits count across the whole run."""
    emit = _Emitter(on_event)
    cancel = cancel or asyncio.Event()
    history = list(resume.messages if resume else messages)
    usage = resume.usage if resume else Usage()
    deadline = time.monotonic() + limits.max_runtime_s
    specs = tools.specs()
    steps = resume.steps if resume else 0
    final_text = ""

    async def finish(term: Termination, error: str | None = None) -> RunResult:
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
        )

    await emit(
        "run_started",
        model=model,
        provider=provider.name,
        limits=limits.model_dump(),
        resumed_at_step=steps if resume else None,
    )

    while True:
        if cancel.is_set():
            return await finish("cancelled")
        if steps >= limits.max_steps:
            return await finish("max_steps")
        if time.monotonic() >= deadline:
            return await finish("deadline")
        if usage.input_tokens + usage.output_tokens >= limits.max_total_tokens:
            return await finish("token_budget")

        steps += 1
        await emit("step_started", step=steps)
        request = ChatRequest(
            model=model,
            messages=history,
            tools=specs,
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

        for i, call in enumerate(calls):
            if cancel.is_set():
                return await finish("cancelled")
            await emit(
                "tool_call", step=steps, id=call.id, name=call.name, arguments=call.arguments
            )
            if i >= limits.max_tool_calls_per_step:
                outcome_content = (
                    '{"error": "limit", "message": "Too many tool calls in one step; skipped."}'
                )
                await emit("tool_result", step=steps, id=call.id, ok=False, error_kind="limit")
            else:
                outcome = await tools.execute(call)
                outcome_content = outcome.as_model_content()
                await emit(
                    "tool_result", step=steps, **outcome.model_dump(exclude={"call_id"}), id=call.id
                )
            history.append(
                Message(
                    role="tool", content=outcome_content, tool_call_id=call.id, tool_name=call.name
                )
            )
        if on_checkpoint is not None:
            await on_checkpoint(Checkpoint(messages=history, steps=steps, usage=usage))


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
