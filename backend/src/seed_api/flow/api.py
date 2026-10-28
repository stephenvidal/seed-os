"""Tasks API: create, inspect, cancel and retry durable tasks. Workers execute them."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field

from ..auth import Principal, require_role
from ..config import Settings, get_settings
from ..core.messages import Usage
from ..errors import ApiError
from .store import Task, TaskEvent, TaskState, TaskStore

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

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
    """A task as clients see it. The checkpoint (full model context) stays server-side."""

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

    @classmethod
    def of(cls, task: Task) -> "TaskView":
        return cls(
            **task.model_dump(exclude={"checkpoint"}),
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
    response: Response,
    principal: AdminOnly,
    store: StoreDep,
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
        if (task.model, task.prompt) != (body.model, body.prompt):
            raise ApiError(
                409,
                "idempotency_conflict",
                "This Idempotency-Key was already used for a different task.",
            )
        response.status_code = 200
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
async def cancel_task(task_id: uuid.UUID, _: AdminOnly, store: StoreDep) -> TaskView:
    """Queued tasks cancel at once; a running task stops at its worker's next heartbeat."""
    await _task(store, task_id)
    task = await store.request_cancel(task_id)
    if task is None:
        raise ApiError(409, "not_cancelable", "The task has already finished.")
    return TaskView.of(task)


@router.post("/{task_id}/retry", response_model=TaskView)
async def retry_task(
    task_id: uuid.UUID, _: AdminOnly, store: StoreDep, settings: SettingsDep
) -> TaskView:
    """Re-queue a failed or canceled task as a fresh run."""
    await _task(store, task_id)
    task = await store.retry(task_id, extra_attempts=settings.task_max_attempts)
    if task is None:
        raise ApiError(409, "not_retryable", "Only failed or canceled tasks can be retried.")
    return TaskView.of(task)
