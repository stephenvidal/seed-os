"""Schedules API: define, list, change, delete and run-now the saved tasks that start
on a timetable (D-029)."""

import uuid
from datetime import time
from typing import Annotated, Self

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from ..auth import AuthStoreDep, Principal, client_ip, require_role
from ..chat.store import ChatError
from ..config import Settings, get_settings
from ..errors import ApiError
from .recurrence import MAX_EVERY_MINUTES, MIN_EVERY_MINUTES, BadTimezone, Kind, zone
from .store import Schedule, ScheduleInput, ScheduleStore

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])

AdminOnly = Annotated[Principal, Depends(require_role("admin"))]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_schedules(request: Request) -> ScheduleStore:
    store: ScheduleStore | None = getattr(request.app.state, "schedule_store", None)
    if store is None:
        raise ApiError(
            503, "database_not_configured", "Schedules need a database. Set SEED_DATABASE_URL."
        )
    return store


SchedulesDep = Annotated[ScheduleStore, Depends(get_schedules)]


class ScheduleIn(BaseModel):
    """A whole definition: creating and changing a schedule both send all of it."""

    name: str = Field(max_length=200)
    prompt: str = Field(max_length=20_000)
    model: str = Field(max_length=200)
    project_id: uuid.UUID | None = None
    kind: Kind
    # interval: every this many minutes (5 to 10080, a week).
    every_minutes: int | None = None
    # daily: at this clock time ("09:30") in `timezone`.
    at_time: time | None = None
    timezone: str = Field(default="UTC", max_length=64)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def name_ok(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 1 <= len(v) <= 80:
            raise ValueError("Give the schedule a name of 1 to 80 characters.")
        return v

    @field_validator("prompt")
    @classmethod
    def prompt_ok(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Say what the task should do.")
        return v

    @field_validator("model")
    @classmethod
    def model_ok(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Choose a model.")
        return v

    @field_validator("at_time")
    @classmethod
    def whole_minutes(cls, v: time | None) -> time | None:
        return None if v is None else v.replace(second=0, microsecond=0, tzinfo=None)

    @field_validator("timezone")
    @classmethod
    def timezone_ok(cls, v: str) -> str:
        try:
            zone(v)
        except BadTimezone as e:
            raise ValueError(str(e)) from e
        return v

    @model_validator(mode="after")
    def timetable_ok(self) -> Self:
        if self.kind == "interval":
            if self.every_minutes is None or not (
                MIN_EVERY_MINUTES <= self.every_minutes <= MAX_EVERY_MINUTES
            ):
                raise ValueError(
                    f"Repeat every {MIN_EVERY_MINUTES} to {MAX_EVERY_MINUTES} minutes."
                )
            if self.at_time is not None:
                raise ValueError("An interval schedule has no time of day.")
        else:
            if self.at_time is None:
                raise ValueError("Say what time of day it runs.")
            if self.every_minutes is not None:
                raise ValueError("A daily schedule has no interval.")
        return self


def _project_missing(e: ChatError) -> ApiError:
    return ApiError(404, e.code, e.message)


@router.get("", response_model=list[Schedule])
async def list_schedules(principal: AdminOnly, store: SchedulesDep) -> list[Schedule]:
    """The signed-in user's schedules, by name."""
    return await store.all(principal.username)


@router.post("", response_model=Schedule, status_code=201)
async def create_schedule(
    body: ScheduleIn,
    request: Request,
    principal: AdminOnly,
    store: SchedulesDep,
    audit: AuthStoreDep,
) -> Schedule:
    try:
        schedule = await store.create(principal.username, ScheduleInput(**body.model_dump()))
    except ChatError as e:
        raise _project_missing(e) from e
    await audit.audit(
        "schedule_created",
        actor=principal.username,
        target=str(schedule.id),
        ip=client_ip(request),
        detail={"name": schedule.name, "kind": schedule.kind},
    )
    return schedule


@router.get("/{schedule_id}", response_model=Schedule)
async def get_schedule(
    schedule_id: uuid.UUID, principal: AdminOnly, store: SchedulesDep
) -> Schedule:
    schedule = await store.get(principal.username, schedule_id)
    if schedule is None:
        raise ApiError(404, "not_found", "No such schedule.")
    return schedule


@router.put("/{schedule_id}", response_model=Schedule)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleIn,
    request: Request,
    principal: AdminOnly,
    store: SchedulesDep,
    audit: AuthStoreDep,
) -> Schedule:
    """Replace a schedule's definition; its next run is worked out afresh."""
    try:
        schedule = await store.update(
            schedule_id, principal.username, ScheduleInput(**body.model_dump())
        )
    except ChatError as e:
        raise _project_missing(e) from e
    if schedule is None:
        raise ApiError(404, "not_found", "No such schedule.")
    await audit.audit(
        "schedule_updated",
        actor=principal.username,
        target=str(schedule_id),
        ip=client_ip(request),
        detail={"name": schedule.name, "kind": schedule.kind, "enabled": schedule.enabled},
    )
    return schedule


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    principal: AdminOnly,
    store: SchedulesDep,
    audit: AuthStoreDep,
) -> Response:
    if not await store.delete(principal.username, schedule_id):
        raise ApiError(404, "not_found", "No such schedule.")
    await audit.audit(
        "schedule_deleted", actor=principal.username, target=str(schedule_id), ip=client_ip(request)
    )
    return Response(status_code=204)


class Started(BaseModel):
    task_id: uuid.UUID


@router.post("/{schedule_id}/run", response_model=Started, status_code=201)
async def run_now(
    schedule_id: uuid.UUID,
    principal: AdminOnly,
    store: SchedulesDep,
    settings: SettingsDep,
) -> Started:
    """Start the schedule's task now. The timetable is unchanged."""
    if settings.ollama_api_key is None:
        raise ApiError(
            503,
            "provider_not_configured",
            "No model provider is configured. Set SEED_OLLAMA_API_KEY.",
        )
    task_id = await store.run_now(principal.username, schedule_id, settings.task_max_attempts)
    if task_id is None:
        raise ApiError(404, "not_found", "No such schedule.")
    return Started(task_id=task_id)
