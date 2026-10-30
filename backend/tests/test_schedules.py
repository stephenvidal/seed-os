"""Schedules (D-029): when they run next, the API, and a worker starting a task for each
due time exactly once."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, time
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.config import Settings
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore, insert_task
from seed_api.flow.worker import Worker
from seed_api.schedules.recurrence import BadTimezone, next_run
from seed_api.schedules.store import ScheduleInput, ScheduleStore

from .conftest import sign_in, start
from .fakes import ScriptedProvider, reply


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# --- When it runs next ------------------------------------------------------------


def test_an_interval_counts_from_now() -> None:
    after = utc(2026, 10, 29, 12, 0)
    assert next_run("interval", after, every_minutes=90) == utc(2026, 10, 29, 13, 30)


def test_a_daily_time_is_the_next_one_on_the_clock_of_its_timezone() -> None:
    at = time(9, 30)
    # Berlin is UTC+1 on 2026-10-29 (summer time ended on the 25th).
    assert next_run("daily", utc(2026, 10, 29, 7, 0), at_time=at, timezone="Europe/Berlin") == utc(
        2026, 10, 29, 8, 30
    )
    # Past it today: tomorrow. Exactly at it: tomorrow (strictly after).
    for after in (utc(2026, 10, 29, 8, 31), utc(2026, 10, 29, 8, 30)):
        assert next_run("daily", after, at_time=at, timezone="Europe/Berlin") == utc(
            2026, 10, 30, 8, 30
        )
    assert next_run("daily", utc(2026, 10, 29, 12, 0), at_time=at) == utc(2026, 10, 30, 9, 30)


def test_a_daily_time_follows_the_clocks_across_a_change() -> None:
    at = time(9, 0)
    berlin = {"at_time": at, "timezone": "Europe/Berlin"}
    # Clocks go forward on 2027-03-28: 09:00 is UTC+1 before, UTC+2 after.
    assert next_run("daily", utc(2027, 3, 27, 9, 0), **berlin) == utc(2027, 3, 28, 7, 0)
    # ...and a 02:30 that does not exist that night runs at the first moment after the gap.
    skipped = {"at_time": time(2, 30), "timezone": "Europe/Berlin"}
    assert next_run("daily", utc(2027, 3, 28, 0, 0), **skipped) == utc(2027, 3, 28, 1, 30)
    # A 02:30 that happens twice (clocks go back on 2026-10-25) runs the first time.
    assert next_run("daily", utc(2026, 10, 24, 23, 0), **skipped) == utc(2026, 10, 25, 0, 30)


def test_next_run_refuses_what_it_cannot_work_out() -> None:
    with pytest.raises(BadTimezone):
        next_run("daily", utc(2026, 1, 1), at_time=time(9), timezone="Mars/Base")
    with pytest.raises(ValueError, match="aware"):
        next_run("interval", datetime(2026, 1, 1), every_minutes=5)
    with pytest.raises(ValueError, match="every_minutes"):
        next_run("interval", utc(2026, 1, 1))
    with pytest.raises(ValueError, match="at_time"):
        next_run("daily", utc(2026, 1, 1))


# --- The API ----------------------------------------------------------------------


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    settings = db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})
    with start(settings) as c:
        yield sign_in(c)


EVERY_HOUR = {
    "name": "  Morning   report ",
    "prompt": " Summarise what changed. ",
    "model": "m-a",
    "kind": "interval",
    "every_minutes": 60,
}
DAILY = {
    "name": "Daily",
    "prompt": "p",
    "model": "m-a",
    "kind": "daily",
    "at_time": "09:30:45",
    "timezone": "Europe/Berlin",
}


def test_schedules_need_a_session(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/schedules").status_code == 401


def test_a_schedule_is_created_listed_changed_and_deleted(api: TestClient, db_url: str) -> None:
    assert api.get("/api/v1/schedules").json() == []
    r = api.post("/api/v1/schedules", json=EVERY_HOUR)
    assert r.status_code == 201, r.text
    s = r.json()
    assert (s["name"], s["prompt"], s["enabled"], s["timezone"]) == (
        "Morning report",
        "Summarise what changed.",
        True,
        "UTC",
    )
    assert s["next_run_at"] is not None and s["last_run_at"] is None and s["last_task_id"] is None
    assert api.get(f"/api/v1/schedules/{s['id']}").json() == s

    daily = api.post("/api/v1/schedules", json=DAILY).json()
    assert daily["at_time"] == "09:30:00"  # whole minutes
    assert [x["name"] for x in api.get("/api/v1/schedules").json()] == ["Daily", "Morning report"]

    off = api.put(f"/api/v1/schedules/{s['id']}", json={**EVERY_HOUR, "enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert off.json()["next_run_at"] is None  # a disabled schedule has no next run
    on = api.put(f"/api/v1/schedules/{s['id']}", json={**DAILY, "name": "Now daily"}).json()
    assert (on["kind"], on["every_minutes"], on["at_time"]) == ("daily", None, "09:30:00")
    assert on["next_run_at"] is not None

    assert api.delete(f"/api/v1/schedules/{s['id']}").status_code == 204
    assert api.delete(f"/api/v1/schedules/{s['id']}").status_code == 404
    assert api.get(f"/api/v1/schedules/{s['id']}").status_code == 404
    assert api.put(f"/api/v1/schedules/{s['id']}", json=EVERY_HOUR).status_code == 404
    with psycopg.connect(db_url) as conn:
        actions = [r[0] for r in conn.execute("SELECT action FROM audit_log ORDER BY id")]
    assert [a for a in actions if a.startswith("schedule_")] == [
        "schedule_created",
        "schedule_created",
        "schedule_updated",
        "schedule_updated",
        "schedule_deleted",
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"every_minutes": 4},
        {"every_minutes": 10081},
        {"every_minutes": None},
        {"at_time": "09:00"},  # an interval has no time of day
        {"kind": "daily"},  # a daily schedule needs a time...
        {"kind": "daily", "at_time": "09:00"},  # ...and has no interval
        {"timezone": "Mars/Base"},
        {"name": "   "},
        {"prompt": "  "},
        {"model": " "},
        {"kind": "weekly"},
    ],
)
def test_a_timetable_that_does_not_make_sense_is_refused(
    api: TestClient, change: dict[str, object]
) -> None:
    assert api.post("/api/v1/schedules", json={**EVERY_HOUR, **change}).status_code == 422


def test_a_schedule_runs_in_one_of_your_projects(api: TestClient) -> None:
    missing = api.post("/api/v1/schedules", json={**EVERY_HOUR, "project_id": str(uuid.uuid4())})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "project_not_found"
    project = api.post("/api/v1/projects", json={"name": "P", "instructions": "Be brief."}).json()
    s = api.post("/api/v1/schedules", json={**EVERY_HOUR, "project_id": project["id"]}).json()
    assert s["project_id"] == project["id"]
    api.delete(f"/api/v1/projects/{project['id']}")  # its schedules go with it
    assert api.get(f"/api/v1/schedules/{s['id']}").status_code == 404


def test_run_now_starts_the_task_and_leaves_the_timetable(api: TestClient) -> None:
    project = api.post("/api/v1/projects", json={"name": "P", "instructions": "Be brief."}).json()
    s = api.post("/api/v1/schedules", json={**EVERY_HOUR, "project_id": project["id"]}).json()
    r = api.post(f"/api/v1/schedules/{s['id']}/run")
    assert r.status_code == 201
    task = api.get(f"/api/v1/tasks/{r.json()['task_id']}").json()
    assert (task["title"], task["prompt"], task["model"], task["state"]) == (
        "Scheduled: Morning report",
        "Summarise what changed.",
        "m-a",
        "queued",
    )
    assert task["project_id"] == project["id"]
    after = api.get(f"/api/v1/schedules/{s['id']}").json()
    assert after["next_run_at"] == s["next_run_at"]  # not moved
    assert (after["last_outcome"], after["last_task_id"]) == ("started", task["id"])
    assert api.post(f"/api/v1/schedules/{uuid.uuid4()}/run").status_code == 404


# --- Starting tasks that are due ---------------------------------------------------


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def pool(db_url: str) -> AsyncIterator[Pool]:
    pool = make_pool(db_url, max_size=6)
    await pool.open(wait=True)
    await migrate(pool)
    yield pool
    await pool.close()


def definition(**over: object) -> ScheduleInput:
    base: dict[str, object] = {
        "name": "Report",
        "prompt": "Write the report.",
        "model": "fake",
        "project_id": None,
        "kind": "interval",
        "every_minutes": 60,
        "at_time": None,
        "timezone": "UTC",
        "enabled": True,
    }
    return ScheduleInput(**{**base, **over})  # type: ignore[arg-type]


async def make_due(pool: Pool, schedule_id: uuid.UUID, minutes_ago: int = 1) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE schedules SET next_run_at = now() - make_interval(mins => %s) WHERE id = %s",
            (minutes_ago, schedule_id),
        )


async def tasks_of(pool: Pool) -> list[dict[str, object]]:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM tasks ORDER BY created_at")
        return list(await cur.fetchall())


@pytest.mark.anyio
async def test_a_due_schedule_starts_one_task_and_sets_the_next_run(pool: Pool) -> None:
    store = ScheduleStore(pool)
    s = await store.create("admin", definition())
    assert await store.fire_due(3) == 0  # not due yet
    await make_due(pool, s.id)
    assert await store.fire_due(3) == 1
    [task] = await tasks_of(pool)
    assert (task["created_by"], task["title"], task["model"], task["prompt"]) == (
        "admin",
        "Scheduled: Report",
        "fake",
        "Write the report.",
    )
    assert (task["state"], task["max_attempts"]) == ("queued", 3)
    after = await store.get("admin", s.id)
    assert after is not None
    assert (after.last_outcome, after.last_task_id) == ("started", task["id"])
    assert after.next_run_at is not None and after.next_run_at > datetime.now(UTC)
    assert await store.fire_due(3) == 0  # and not again until then
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT actor, detail FROM audit_log WHERE action LIKE 'schedule%'"
        )
        [(actor, detail)] = [(r["actor"], r["detail"]) for r in await cur.fetchall()]
    assert actor is None and detail["task_id"] == str(task["id"]) and detail["by"] == "schedule"


@pytest.mark.anyio
async def test_workers_polling_together_start_a_due_time_once(pool: Pool) -> None:
    store = ScheduleStore(pool)
    s = await store.create("admin", definition())
    await make_due(pool, s.id)
    started = await asyncio.gather(*(store.fire_due(3) for _ in range(6)))
    assert sum(started) == 1 and len(await tasks_of(pool)) == 1


@pytest.mark.anyio
async def test_missed_runs_start_one_task_not_one_each(pool: Pool) -> None:
    store = ScheduleStore(pool)
    s = await store.create("admin", definition(every_minutes=5))
    await make_due(pool, s.id, minutes_ago=3 * 24 * 60)
    assert await store.fire_due(3) == 1
    assert len(await tasks_of(pool)) == 1
    after = await store.get("admin", s.id)
    assert after is not None and after.next_run_at is not None
    assert after.next_run_at > datetime.now(UTC)  # counted from now, not from the missed time
    assert await store.fire_due(3) == 0


@pytest.mark.anyio
async def test_a_due_time_that_already_started_its_task_starts_no_second(pool: Pool) -> None:
    store = ScheduleStore(pool)
    s = await store.create("admin", definition())
    await make_due(pool, s.id)
    due = (await store.get("admin", s.id)).next_run_at  # type: ignore[union-attr]
    assert due is not None
    async with pool.connection() as conn:
        await insert_task(
            conn,
            created_by="admin",
            title="earlier",
            model="fake",
            prompt="Write the report.",
            max_attempts=3,
            idempotency_key=f"schedule:{s.id}:{due.astimezone(UTC).isoformat()}",
        )
    assert await store.fire_due(3) == 0
    assert len(await tasks_of(pool)) == 1


@pytest.mark.anyio
async def test_a_run_is_skipped_while_the_last_task_is_still_going(pool: Pool) -> None:
    store = ScheduleStore(pool)
    s = await store.create("admin", definition())
    await make_due(pool, s.id)
    await store.fire_due(3)
    [first] = await tasks_of(pool)
    await make_due(pool, s.id)
    assert await store.fire_due(3) == 0  # still queued
    after = await store.get("admin", s.id)
    assert after is not None and after.last_outcome == "skipped_busy"
    assert after.last_task_id == first["id"]  # still the one that is going
    assert after.next_run_at is not None and after.next_run_at > datetime.now(UTC)

    async with pool.connection() as conn:  # waiting for a person's approval is still going
        await conn.execute(
            "UPDATE tasks SET state = 'waiting', awaiting_approval = "
            """'{"id": "c", "name": "run_command", "arguments": {}}'::jsonb"""
        )
    await make_due(pool, s.id)
    assert await store.fire_due(3) == 0
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE tasks SET state = 'completed', awaiting_approval = NULL, finished_at = now()"
        )
    await make_due(pool, s.id)
    assert await store.fire_due(3) == 1
    assert len(await tasks_of(pool)) == 2


@pytest.mark.anyio
async def test_a_disabled_schedule_never_fires_and_a_project_task_gets_its_context(
    pool: Pool,
) -> None:
    from seed_api.projects.store import ProjectStore

    store = ScheduleStore(pool)
    off = await store.create("admin", definition(name="Off", enabled=False))
    async with pool.connection() as conn:  # even with a time in the past
        await conn.execute("UPDATE schedules SET next_run_at = NULL WHERE id = %s", (off.id,))
    project = await ProjectStore(pool).create(owner="admin", name="P", instructions="Be brief.")
    on = await store.create("admin", definition(name="On", project_id=project.id))
    await make_due(pool, on.id)
    assert await store.fire_due(3) == 1
    [task] = await tasks_of(pool)
    assert task["title"] == "Scheduled: On"
    assert (task["project_id"], task["instructions"]) == (project.id, "Be brief.")


@pytest.mark.anyio
async def test_a_worker_starts_a_due_task_and_runs_it(pool: Pool, tmp_path: Path) -> None:
    store = ScheduleStore(pool)
    s = await store.create("admin", definition())
    await make_due(pool, s.id)
    provider = ScriptedProvider([reply("Here is the report.")])
    settings = Settings(workspace_root=str(tmp_path), worker_lease_seconds=3)
    worker = Worker(TaskStore(pool), settings, lambda: provider, worker_id="w")
    assert await worker.run_once()  # starts the task, then claims and runs it
    [task] = await tasks_of(pool)
    assert (task["state"], task["result_text"]) == ("completed", "Here is the report.")
    assert provider.requests[0].messages[-1].content == "Write the report."
