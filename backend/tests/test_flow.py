"""SEED Flow against a real Postgres: state machine, leases, recovery, cancellation."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from seed_api.auth import AuthStore, bootstrap_admin
from seed_api.config import Settings, get_settings
from seed_api.core.pricing import ModelPrice
from seed_api.core.providers.base import ProviderError
from seed_api.flow import api as tasks_api
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import LeaseLost, Task, TaskStore
from seed_api.flow.worker import Worker
from seed_api.main import create_app
from seed_api.sandbox.client import SandboxClient
from seed_api.sandbox.server import create_sandbox_app

from .fakes import ScriptedProvider, Step, calls, reply

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def pool(db_url: str) -> AsyncIterator[Pool]:
    pool = make_pool(db_url, max_size=4)
    await pool.open(wait=True)
    assert await migrate(pool) == [
        "0001_tasks",
        "0002_auth",
        "0003_conversations",
        "0004_approvals",
        "0005_versions",
        "0006_artifacts",
        "0007_previews",
        "0008_projects",
        "0009_memory",
        "0010_knowledge",
        "0011_summaries",
        "0012_agents",
        "0013_delegation",
        "0014_delegation_depth",
        "0015_tool_result_index",
        "0016_schedules",
        "0017_notifications",
        "0018_telegram",
        "0019_telegram_chat",
        "0020_skills",
        "0021_agent_skills",
        "0022_skill_writer",
        "0023_verification",
        "0024_recall",
        "0025_owner_memory",
    ]
    yield pool
    await pool.close()


@pytest.fixture
def store(pool: Pool) -> TaskStore:
    return TaskStore(pool)


@pytest.fixture
def wsettings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=str(tmp_path), worker_lease_seconds=3, task_max_attempts=3)


async def new_task(store: TaskStore, *, max_attempts: int = 3, key: str | None = None) -> Task:
    task, _ = await store.create(
        created_by="admin",
        title="t",
        model="fake",
        prompt="write a.txt",
        max_attempts=max_attempts,
        idempotency_key=key,
    )
    return task


def worker(store: TaskStore, settings: Settings, script: list[Step], name: str) -> Worker:
    provider = ScriptedProvider(script)
    w = Worker(store, settings, lambda: provider, worker_id=name)
    w.provider = provider  # type: ignore[attr-defined]
    return w


async def expire_lease(pool: Pool, task_id: uuid.UUID) -> None:
    """Stand-in for the lease running out after a worker died."""
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE tasks SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
            (task_id,),
        )


async def until(predicate, timeout: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    deadline = asyncio.get_running_loop().time() + timeout
    while not await predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.02)


async def test_migrations_are_idempotent(pool: Pool) -> None:
    assert await migrate(pool) == []


async def test_worker_completes_task_with_ordered_audit_log(
    store: TaskStore, wsettings: Settings, tmp_path: Path
) -> None:
    task = await new_task(store)
    w = worker(
        store,
        wsettings,
        [calls(("write_file", {"path": "a.txt", "content": "hi"})), reply("Wrote a.txt")],
        "w1",
    )
    assert await w.run_once() is True
    assert await w.run_once() is False  # nothing left to claim

    done = await store.get(task.id)
    assert done is not None
    assert done.state == "completed" and done.termination == "completed"
    assert done.result_text == "Wrote a.txt"
    assert done.usage.input_tokens == 20 and done.attempt == 1 and done.lease_owner is None
    assert (tmp_path / str(task.id) / "a.txt").read_text() == "hi"

    events = await store.events(task.id, after=0, limit=100)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    types = [e.type for e in events]
    assert types[:3] == ["task_created", "attempt_started", "run_started"]
    assert types[-1] == "run_finished" and "tool_result" in types
    # The step with tool results is checkpointed, and the log says so after them.
    saved = [e for e in events if e.type == "checkpoint_saved"]
    assert [(e.data, e.attempt) for e in saved] == [({"steps": 1, "pending": 0}, 1)]
    assert types.index("checkpoint_saved") > types.index("tool_result")
    assert done.last_seq == len(events)
    assert len(await store.events(task.id, after=3, limit=2)) == 2


async def test_crashed_worker_task_resumes_from_checkpoint(
    pool: Pool, store: TaskStore, wsettings: Settings, tmp_path: Path
) -> None:
    task = await new_task(store)
    a = worker(
        store, wsettings, [calls(("write_file", {"path": "a.txt", "content": "1"})), 30.0], "a"
    )
    running = asyncio.create_task(a.run_once())

    async def checkpointed() -> bool:
        t = await store.get(task.id)
        return t is not None and t.checkpoint is not None

    await until(checkpointed)
    running.cancel()  # the process dies: no further writes from worker a
    with pytest.raises(asyncio.CancelledError):
        await running
    still = await store.get(task.id)
    assert still is not None and still.state == "running" and still.lease_owner == "a"

    await expire_lease(pool, task.id)
    b = worker(store, wsettings, [reply("Finished")], "b")
    assert await b.run_once() is True

    done = await store.get(task.id)
    assert done is not None and done.state == "completed" and done.attempt == 2
    # b continued the conversation instead of starting over: step 1's tool result is there.
    resumed_request = b.provider.requests[0]  # type: ignore[attr-defined]
    assert [m.role for m in resumed_request.messages] == ["system", "user", "assistant", "tool"]
    assert done.usage.input_tokens == 20  # step 1 from a + step 2 from b
    assert (tmp_path / str(task.id) / "a.txt").read_text() == "1"
    events = await store.events(task.id, after=0, limit=100)
    started = [e.data for e in events if e.type == "attempt_started"]
    assert started == [
        {"attempt": 1, "worker": "a", "resumed_at_step": None},
        {"attempt": 2, "worker": "b", "resumed_at_step": 1},
    ]


async def test_stale_worker_is_fenced_out(pool: Pool, store: TaskStore) -> None:
    task = await new_task(store)
    claim_a = await store.claim("a", 30)
    assert claim_a is not None
    await expire_lease(pool, task.id)
    claim_b = await store.claim("b", 30)
    assert claim_b is not None and claim_b[1].attempt == 2

    lease_a = claim_a[1]
    with pytest.raises(LeaseLost):
        await store.append_event(lease_a, "text_delta", {"text": "late"})
    with pytest.raises(LeaseLost):
        await store.heartbeat(lease_a, 30)
    with pytest.raises(LeaseLost):
        await store.finish(
            lease_a,
            state="completed",
            termination="completed",
            error=None,
            result_text="",
            usage=claim_b[0].usage,
        )
    after = await store.get(task.id)
    assert after is not None and after.state == "running" and after.lease_owner == "b"


async def test_task_out_of_attempts_is_dead_lettered(pool: Pool, store: TaskStore) -> None:
    task = await new_task(store, max_attempts=1)
    assert await store.claim("a", 30) is not None
    await expire_lease(pool, task.id)
    assert await store.claim("b", 30) is None  # not reclaimable: no attempts left
    assert await store.sweep() == 1
    dead = await store.get(task.id)
    assert dead is not None and dead.state == "failed" and dead.termination == "abandoned"
    assert dead.error and "every allowed attempt" in dead.error


async def test_cancel_reaches_a_running_task(store: TaskStore, wsettings: Settings) -> None:
    task = await new_task(store)
    w = worker(store, wsettings, [30.0], "w")
    running = asyncio.create_task(w.run_once())

    async def is_running() -> bool:
        t = await store.get(task.id)
        return t is not None and t.state == "running"

    await until(is_running)
    flagged = await store.request_cancel(task.id)
    assert flagged is not None and flagged.state == "running" and flagged.cancel_requested
    await asyncio.wait_for(running, timeout=5)  # next heartbeat (≤1 s) stops the run
    done = await store.get(task.id)
    assert done is not None and done.state == "canceled" and done.termination == "cancelled"


async def test_cancel_queued_task_is_immediate_and_final(store: TaskStore) -> None:
    task = await new_task(store)
    canceled = await store.request_cancel(task.id)
    assert canceled is not None and canceled.state == "canceled"
    assert await store.request_cancel(task.id) is None
    assert await store.claim("w", 30) is None


async def test_graceful_shutdown_hands_task_back_with_checkpoint(
    store: TaskStore, wsettings: Settings
) -> None:
    task = await new_task(store)
    a = worker(
        store, wsettings, [calls(("write_file", {"path": "a.txt", "content": "1"})), 30.0], "a"
    )
    running = asyncio.create_task(a.run_once())

    async def checkpointed() -> bool:
        t = await store.get(task.id)
        return t is not None and t.checkpoint is not None

    await until(checkpointed)
    a.stop.set()  # SIGTERM
    await asyncio.wait_for(running, timeout=5)
    back = await store.get(task.id)
    assert back is not None and back.state == "queued" and back.attempt == 0
    assert back.checkpoint is not None and back.checkpoint.steps == 1

    b = worker(store, wsettings, [reply("Done")], "b")
    assert await b.run_once() is True
    done = await store.get(task.id)
    assert done is not None and done.state == "completed" and done.attempt == 1


async def test_failed_task_can_be_retried_from_scratch(
    store: TaskStore, wsettings: Settings
) -> None:
    task = await new_task(store)
    w = worker(store, wsettings, [ProviderError("fake", "auth", "bad key")], "w")
    await w.run_once()
    failed = await store.get(task.id)
    assert failed is not None and failed.state == "failed"
    assert failed.termination == "provider_error" and failed.error == "auth: bad key"
    assert await store.retry(uuid.uuid4(), extra_attempts=3) is None

    queued = await store.retry(task.id, extra_attempts=3)
    assert queued is not None and queued.state == "queued" and queued.max_attempts == 4
    assert queued.error is None and queued.checkpoint is None
    w2 = worker(store, wsettings, [reply("ok")], "w2")
    assert await w2.run_once() is True
    done = await store.get(task.id)
    assert done is not None and done.state == "completed" and done.attempt == 2
    assert await store.retry(task.id, extra_attempts=3) is None  # completed is final


async def test_idempotency_key_returns_the_same_task(store: TaskStore) -> None:
    first = await new_task(store, key="k-1")
    again, created = await store.create(
        created_by="admin",
        title="t",
        model="fake",
        prompt="other",
        max_attempts=3,
        idempotency_key="k-1",
    )
    assert created is False and again.id == first.id
    other = await new_task(store, key="k-2")
    assert other.id != first.id


async def test_stream_delivers_events_written_after_it_opened(
    store: TaskStore, wsettings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks_api, "STREAM_POLL_S", 0.02)
    settings = wsettings.model_copy(update={"admin_password": SecretStr("a-long-password")})
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.task_store = store
    app.state.auth_store = AuthStore(store.pool)
    await bootstrap_admin(app.state.auth_store, settings)
    task = await new_task(store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        login = {"username": "admin", "password": "a-long-password"}
        assert (await client.post("/api/v1/auth/login", json=login)).status_code == 200
        stream = asyncio.create_task(client.get(f"/api/v1/tasks/{task.id}/stream"))
        await asyncio.sleep(0.1)  # the stream is open and idle before any work happens
        assert not stream.done()
        await worker(store, wsettings, [reply("hello")], "w").run_once()
        body = (await asyncio.wait_for(stream, timeout=5)).text
    types = [
        json.loads(line[6:])["type"] for line in body.splitlines() if line.startswith('data: {"seq')
    ]
    assert types[0] == "task_created" and types[-1] == "run_finished"
    assert "text_delta" in types and body.rstrip().endswith('data: {"state": "completed"}')


async def test_worker_runs_commands_in_the_sandbox(store: TaskStore, tmp_path: Path) -> None:
    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()
    settings = Settings(
        workspace_root=str(tmp_path / "local"),
        sandbox_root=str(sandbox_root),
        sandbox_isolate_users=False,
        sandbox_command_timeout_seconds=5,
    )
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_sandbox_app(settings)), base_url="http://sb"
    )
    task = await new_task(store)
    provider = ScriptedProvider(
        [calls(("run_command", {"command": "echo built > out.txt; cat out.txt"})), reply("ok")]
    )
    w = Worker(store, settings, lambda: provider, sandbox=SandboxClient(http), worker_id="w")
    assert await w.run_once() is True
    # Commands wait for a person's approval by default; nothing has run yet.
    waiting = await store.get(task.id)
    assert waiting is not None and waiting.state == "waiting" and waiting.attempt == 0
    assert waiting.awaiting_approval is not None
    assert waiting.awaiting_approval.name == "run_command"
    assert not (sandbox_root / str(task.id) / "out.txt").exists()
    assert await w.run_once() is False  # a waiting task is not claimable
    decided = await store.decide(
        task.id, call_id=waiting.awaiting_approval.id, approved=True, by="admin"
    )
    assert decided is not None and decided.state == "queued"
    assert await w.run_once() is True
    await http.aclose()
    done = await store.get(task.id)
    assert done is not None and done.state == "completed" and done.attempt == 1
    events = await store.events(task.id, after=0, limit=100)
    types = [e.type for e in events]
    assert types.count("tool_call") == 1 and types.count("tool_result") == 1
    assert types.index("approval_requested") < types.index("approval_decided")
    # Saved at the pause with the call still to run, then again once it has run.
    saved = [e.data for e in events if e.type == "checkpoint_saved"]
    assert saved == [{"steps": 1, "pending": 1}, {"steps": 1, "pending": 0}]
    result = next(e.data for e in events if e.type == "tool_result")
    assert result["ok"] and result["output"]["stdout"] == "built\n"
    assert (sandbox_root / str(task.id) / "out.txt").read_text() == "built\n"
    assert not (tmp_path / "local").exists()  # nothing touched the worker's own disk


# D-035: spend limits. The fake model costs $1 per token, so one `reply` is $20.
DEAR = {"fake": ModelPrice(input_per_m=1_000_000, output_per_m=1_000_000)}


async def test_task_stops_when_its_run_costs_the_limit(store: TaskStore, tmp_path: Path) -> None:
    settings = Settings(workspace_root=str(tmp_path), model_prices=DEAR, budget_task_usd=30)
    task = await new_task(store)
    loop = [calls(("list_files", {})) for _ in range(5)]
    assert await worker(store, settings, loop, "w1").run_once() is True
    done = await store.get(task.id)
    assert done is not None
    assert (done.state, done.termination) == ("failed", "cost_budget")
    assert done.usage.input_tokens == 20  # stopped after two steps of $20 each


async def test_daily_limit_refuses_the_next_task_without_calling_the_model(
    store: TaskStore, tmp_path: Path
) -> None:
    settings = Settings(workspace_root=str(tmp_path), model_prices=DEAR, budget_daily_usd=30)
    first, second = await new_task(store), await new_task(store)
    w = worker(store, settings, [reply("one"), reply("two")], "w1")
    await w.run_once()  # $20 spent, under the limit
    await w.run_once()  # $40 spent
    third = await new_task(store)
    await w.run_once()
    done = [await store.get(t.id) for t in (first, second, third)]
    assert [d.state for d in done if d] == ["completed", "completed", "failed"]
    refused = done[2]
    assert refused is not None and refused.termination == "daily_budget"
    assert refused.error is not None and "$30.00" in refused.error
    assert len(w.provider.requests) == 2  # type: ignore[attr-defined]


async def test_a_limit_with_an_unpriced_model_refuses_rather_than_ignores(
    store: TaskStore, tmp_path: Path
) -> None:
    settings = Settings(workspace_root=str(tmp_path), budget_daily_usd=5)
    task = await new_task(store)
    w = worker(store, settings, [reply("hi")], "w1")
    await w.run_once()
    done = await store.get(task.id)
    assert done is not None and done.termination == "price_unknown"
    assert done.error is not None and "SEED_MODEL_PRICES" in done.error
    assert w.provider.requests == []  # type: ignore[attr-defined]


async def test_without_limits_cost_is_not_checked(store: TaskStore, tmp_path: Path) -> None:
    settings = Settings(workspace_root=str(tmp_path))
    task = await new_task(store)
    await worker(store, settings, [reply("hi")], "w1").run_once()
    done = await store.get(task.id)
    assert done is not None and done.state == "completed"


async def test_a_task_can_search_the_web_and_gets_fenced_content(
    store: TaskStore, wsettings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-037: the worker offers web_search, and what it returns is fenced."""
    from seed_api.web.tools import WebClient

    def web(_: httpx.Request) -> httpx.Response:
        body = {"results": [{"title": "T", "url": "https://a.test", "content": "page text"}]}
        return httpx.Response(200, json=body)

    client = WebClient("https://web.test", "k", transport=httpx.MockTransport(web))
    monkeypatch.setattr(Worker, "_web", lambda self: client)
    task = await new_task(store)
    w = worker(store, wsettings, [calls(("web_search", {"query": "q"})), reply("done")], "w1")
    await w.run_once()
    done = await store.get(task.id)
    assert done is not None and done.state == "completed"
    results = [
        e.data for e in await store.events(task.id, after=0, limit=100) if e.type == "tool_result"
    ]
    assert results[0]["ok"] is True and "UNTRUSTED CONTENT" in json.dumps(results[0])


async def test_a_task_uses_mcp_tools_and_skips_a_server_that_is_gone(
    store: TaskStore, tmp_path: Path, mcp_url: str
) -> None:
    """D-041: a configured server's tools are offered and their results fenced; a
    server that does not answer is recorded and the task goes on without it."""
    from seed_api.config import McpServer

    from .mcp_server import free_port

    settings = Settings(
        workspace_root=str(tmp_path),
        mcp_servers=[
            McpServer(name="calc", url=mcp_url, approval="never"),
            McpServer(name="gone", url=f"http://127.0.0.1:{free_port()}/mcp"),
        ],
        mcp_connect_timeout_seconds=5,
    )
    task = await new_task(store)
    w = worker(store, settings, [calls(("mcp_calc_add", {"a": 2, "b": 40})), reply("42")], "w1")
    await w.run_once()
    done = await store.get(task.id)
    assert done is not None and done.state == "completed"
    offered = {t.name for t in w.provider.requests[0].tools}  # type: ignore[attr-defined]
    assert "mcp_calc_add" in offered and not any(n.startswith("mcp_gone") for n in offered)
    events = await store.events(task.id, after=0, limit=100)
    gone = [e.data for e in events if e.type == "mcp_unavailable"]
    assert gone and gone[0]["server"] == "gone"
    results = [e.data for e in events if e.type == "tool_result"]
    assert results[0]["ok"] is True
    assert "UNTRUSTED CONTENT" in json.dumps(results[0]) and "42" in json.dumps(results[0])


# D-038: the owner's check decides, not the agent.
async def checked(
    store: TaskStore,
    tmp_path: Path,
    check: str,
    script: list[Step],
    *,
    timeout: float = 5,
    sandbox: bool = True,
) -> tuple[Task, Worker]:
    root = tmp_path / "sandbox"
    root.mkdir()
    settings = Settings(
        workspace_root=str(tmp_path / "local"),
        sandbox_root=str(root),
        sandbox_isolate_users=False,
        sandbox_command_timeout_seconds=timeout,
    )
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_sandbox_app(settings)), base_url="http://sb"
    )
    task, _ = await store.create(
        created_by="admin",
        title="t",
        model="fake",
        prompt="write a.txt",
        max_attempts=3,
        idempotency_key=None,
        check_command=check,
    )
    provider = ScriptedProvider(script)
    w = Worker(
        store,
        settings,
        lambda: provider,
        sandbox=SandboxClient(http) if sandbox else None,
        worker_id="w",
    )
    w.provider = provider  # type: ignore[attr-defined]
    assert await w.run_once() is True
    await http.aclose()
    done = await store.get(task.id)
    assert done is not None
    return done, w


def write(content: str) -> Step:
    return calls(("write_file", {"path": "a.txt", "content": content}))


async def test_a_passing_check_completes_the_task_and_is_recorded(
    store: TaskStore, tmp_path: Path
) -> None:
    done, _ = await checked(store, tmp_path, "grep -q fine a.txt", [write("fine"), reply("Done")])
    assert (done.state, done.termination) == ("completed", "completed")
    assert done.verification is not None and done.verification.passed
    assert done.verification.exit_code == 0 and done.verification.command == "grep -q fine a.txt"
    events = [e.type for e in await store.events(done.id, after=0, limit=100)]
    assert events.count("verification") == 1


async def test_a_failing_check_fails_the_task_though_the_agent_said_done(
    store: TaskStore, tmp_path: Path
) -> None:
    script = [write("broken"), reply("All done, it works!")]
    done, _ = await checked(store, tmp_path, "echo no >&2; grep -q fine a.txt", script)
    assert (done.state, done.termination) == ("failed", "check_failed")
    assert done.result_text == "All done, it works!"  # the agent's answer is kept to read
    assert done.error is not None and "exit code 1" in done.error
    v = done.verification
    assert v is not None and not v.passed and v.exit_code == 1 and "no" in v.stderr


async def test_a_check_that_runs_out_of_time_fails(store: TaskStore, tmp_path: Path) -> None:
    done, _ = await checked(store, tmp_path, "sleep 5", [reply("Done")], timeout=1)
    assert done.termination == "check_failed" and done.error is not None
    assert "ran out of time" in done.error
    assert done.verification is not None and done.verification.timed_out


async def test_a_check_without_a_sandbox_refuses_before_calling_the_model(
    store: TaskStore, tmp_path: Path
) -> None:
    done, w = await checked(store, tmp_path, "true", [reply("Done")], sandbox=False)
    assert done.termination == "check_unavailable" and done.state == "failed"
    assert w.provider.requests == []  # type: ignore[attr-defined]


async def test_the_check_does_not_run_when_the_run_did_not_finish(
    store: TaskStore, tmp_path: Path
) -> None:
    loop = [calls(("list_files", {})) for _ in range(9)]
    done, _ = await checked(store, tmp_path, "true", loop)
    assert done.termination == "max_steps" and done.verification is None
