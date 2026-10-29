"""Tasks API: create, inspect, cancel and retry durable tasks. Workers execute them."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..auth import AuthStoreDep, Principal, client_ip, require_role
from ..config import Settings, get_settings
from ..core.messages import ToolCall, Usage
from ..errors import ApiError
from .store import TERMINAL, Task, TaskEvent, TaskState, TaskStore

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
STREAM_POLL_S = 0.5
KEEPALIVE_S = 15.0

AdminOnly = Annotated[Principal, Depends(require_role("admin"))]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_store(request: Request) -> TaskStore:
    store: TaskStore | None = getattr(request.app.state, "task_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Tasks need a database. Set SEED_DATABASE_URL."
        )
    return store


StoreDep = Annotated[TaskStore, Depends(get_store)]


class TaskView(BaseModel):
    """A task as clients see it. The checkpoint and a chat turn's context (full
    model input) stay server-side."""

    id: uuid.UUID
    title: str
    model: str
    prompt: str
    state: TaskState
    attempt: int
    max_attempts: int
    cancel_requested: bool
    termination: str | None
    error: str | None
    result_text: str | None
    usage: Usage
    last_seq: int
    resumable_from_step: int | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # Set when the task is a chat turn: its conversation and position in it.
    conversation_id: uuid.UUID | None
    turn: int | None
    # Set while state is waiting: the tool call that needs a person's decision.
    awaiting_approval: ToolCall | None

    @classmethod
    def of(cls, task: Task) -> "TaskView":
        return cls(
            **task.model_dump(include=set(cls.model_fields) - {"resumable_from_step"}),
            resumable_from_step=task.checkpoint.steps if task.checkpoint else None,
        )


class CreateTask(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20_000)
    title: str | None = Field(default=None, min_length=1, max_length=200)


class EventsPage(BaseModel):
    events: list[TaskEvent]
    last_seq: int
    state: TaskState


async def _task(store: TaskStore, task_id: uuid.UUID) -> Task:
    task = await store.get(task_id)
    if task is None:
        raise ApiError(404, "not_found", "No such task.")
    return task


@router.post("", response_model=TaskView, status_code=201)
async def create_task(
    body: CreateTask,
    request: Request,
    response: Response,
    principal: AdminOnly,
    store: StoreDep,
    audit: AuthStoreDep,
    settings: SettingsDep,
    idempotency_key: Annotated[
        str | None, Header(min_length=1, max_length=200, pattern=r"^[\x21-\x7e]+$")
    ] = None,
) -> TaskView:
    if settings.ollama_api_key is None:
        raise ApiError(
            503,
            "provider_not_configured",
            "No model provider is configured. Set SEED_OLLAMA_API_KEY.",
        )
    task, created = await store.create(
        created_by=principal.username,
        title=body.title or " ".join(body.prompt.split())[:80],
        model=body.model,
        prompt=body.prompt,
        max_attempts=settings.task_max_attempts,
        idempotency_key=idempotency_key,
    )
    if not created:
        if (task.model, task.prompt, task.conversation_id) != (body.model, body.prompt, None):
            raise ApiError(
                409,
                "idempotency_conflict",
                "This Idempotency-Key was already used for a different task.",
            )
        response.status_code = 200
    else:
        await audit.audit(
            "task_created", actor=principal.username, target=str(task.id), ip=client_ip(request)
        )
    return TaskView.of(task)


@router.get("", response_model=list[TaskView])
async def list_tasks(
    _: AdminOnly,
    store: StoreDep,
    state: TaskState | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[TaskView]:
    return [TaskView.of(t) for t in await store.list_tasks(limit=limit, state=state)]


@router.get("/{task_id}", response_model=TaskView)
async def get_task(task_id: uuid.UUID, _: AdminOnly, store: StoreDep) -> TaskView:
    return TaskView.of(await _task(store, task_id))


@router.get("/{task_id}/events", response_model=EventsPage)
async def task_events(
    task_id: uuid.UUID,
    _: AdminOnly,
    store: StoreDep,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> EventsPage:
    task = await _task(store, task_id)
    events = await store.events(task_id, after=after, limit=limit)
    return EventsPage(events=events, last_seq=task.last_seq, state=task.state)


@router.post("/{task_id}/cancel", response_model=TaskView)
async def cancel_task(
    task_id: uuid.UUID, request: Request, principal: AdminOnly, store: StoreDep, audit: AuthStoreDep
) -> TaskView:
    """Queued tasks cancel at once; a running task stops at its worker's next heartbeat."""
    await _task(store, task_id)
    task = await store.request_cancel(task_id)
    if task is None:
        raise ApiError(409, "not_cancelable", "The task has already finished.")
    await audit.audit(
        "task_canceled", actor=principal.username, target=str(task_id), ip=client_ip(request)
    )
    return TaskView.of(task)


class Decide(BaseModel):
    call_id: str = Field(min_length=1, max_length=200)
    approve: bool


@router.post("/{task_id}/decision", response_model=TaskView)
async def decide(
    task_id: uuid.UUID,
    body: Decide,
    request: Request,
    principal: AdminOnly,
    store: StoreDep,
    audit: AuthStoreDep,
) -> TaskView:
    """Approve or deny the tool call a waiting task waits for. The task is queued
    and resumes where it stopped; a denied call is reported to the model."""
    call = (await _task(store, task_id)).awaiting_approval
    task = await store.decide(
        task_id, call_id=body.call_id, approved=body.approve, by=principal.username
    )
    if task is None:
        raise ApiError(409, "not_waiting", "The task is not waiting for a decision on that call.")
    await audit.audit(
        "tool_approved" if body.approve else "tool_denied",
        actor=principal.username,
        target=f"{task_id}/{body.call_id}",
        ip=client_ip(request),
        detail={"tool": call.name, "arguments": call.arguments} if call else None,
    )
    return TaskView.of(task)


@router.post("/{task_id}/retry", response_model=TaskView)
async def retry_task(
    task_id: uuid.UUID,
    request: Request,
    principal: AdminOnly,
    store: StoreDep,
    audit: AuthStoreDep,
    settings: SettingsDep,
) -> TaskView:
    """Re-queue a failed or canceled task as a fresh run."""
    await _task(store, task_id)
    task = await store.retry(task_id, extra_attempts=settings.task_max_attempts)
    if task is None:
        raise ApiError(409, "not_retryable", "Only failed or canceled tasks can be retried.")
    await audit.audit(
        "task_retried", actor=principal.username, target=str(task_id), ip=client_ip(request)
    )
    return TaskView.of(task)


@router.get("/{task_id}/stream")
async def stream_task(
    task_id: uuid.UUID,
    request: Request,
    _: AdminOnly,
    store: StoreDep,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(max_length=20)] = None,
) -> StreamingResponse:
    """Server-Sent Events for one task (ADR-0003). Each event is the stored row,
    with `id:` = its seq, so a reconnecting EventSource resumes via Last-Event-ID
    without gaps or duplicates. Ends with `event: end` once the task is finished
    and every event has been sent. The stream only reads; closing it never
    affects the task."""
    await _task(store, task_id)
    start = max(after, int(last_event_id) if last_event_id and last_event_id.isdigit() else 0)

    async def events() -> AsyncIterator[bytes]:
        seq, idle = start, 0.0
        yield b"retry: 2000\n\n"
        while not await request.is_disconnected():
            batch = await store.events(task_id, after=seq, limit=500)
            for e in batch:
                seq = e.seq
                yield f"id: {e.seq}\ndata: {e.model_dump_json()}\n\n".encode()
            if batch:
                idle = 0.0
                continue
            task = await store.get(task_id)
            if task is None or (task.state in TERMINAL and task.last_seq <= seq):
                end = json.dumps({"state": task.state if task else None})
                yield f"event: end\ndata: {end}\n\n".encode()
                return
            await asyncio.sleep(STREAM_POLL_S)
            idle += STREAM_POLL_S
            if idle >= KEEPALIVE_S:
                yield b": keepalive\n\n"
                idle = 0.0

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
