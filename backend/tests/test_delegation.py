"""Delegation (D-025): the assistant hands a sub-task to an agent, which runs as a
task of its own; the assistant waits, durably, and carries on with the report."""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest

from seed_api.agents.store import AgentStore
from seed_api.chat.store import ChatStore
from seed_api.config import Settings
from seed_api.core.providers.base import ProviderError
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import Task, TaskStore
from seed_api.flow.worker import Worker
from seed_api.projects.store import ProjectStore

from .fakes import ScriptedProvider, Step, calls, reply

ASK = {
    "agent": "researcher",  # names match ignoring case
    "task": "Read notes.md and list the open questions.",
    "deliverable": "A bulleted list of questions.",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def pool(db_url: str) -> AsyncIterator[Pool]:
    pool = make_pool(db_url, max_size=4)
    await pool.open(wait=True)
    await migrate(pool)
    yield pool
    await pool.close()


class Runner:
    """Runs queued tasks one at a time, each with its own scripted provider."""

    def __init__(self, pool: Pool, tmp_path: Path, **settings: object) -> None:
        self.tasks = TaskStore(pool)
        self.settings = Settings(
            workspace_root=str(tmp_path),
            worker_lease_seconds=3,
            **settings,  # type: ignore[arg-type]
        )
        self.providers: list[ScriptedProvider] = []

    async def next(self, *script: Step) -> ScriptedProvider:
        provider = ScriptedProvider(list(script))
        self.providers.append(provider)
        worker = Worker(self.tasks, self.settings, lambda: provider, worker_id="w")
        assert await worker.run_once()
        assert provider.script == []
        return provider

    async def task(self, task_id: uuid.UUID) -> Task:
        task = await self.tasks.get(task_id)
        assert task is not None
        return task

    async def events(self, task_id: uuid.UUID) -> list[tuple[str, dict[str, object]]]:
        return [(e.type, e.data) for e in await self.tasks.events(task_id, after=0, limit=500)]


async def children(pool: Pool, parent: uuid.UUID) -> list[Task]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT * FROM tasks WHERE parent_task_id = %s ORDER BY created_at", (parent,)
        )
        return [Task.model_validate(r) for r in await cur.fetchall()]


async def start_turn(pool: Pool, prompt: str = "What is still open?", **kw: object) -> Task:
    _, turn, _ = await ChatStore(pool).start(
        owner="admin",
        model="fake",
        prompt=prompt,
        max_attempts=3,
        idempotency_key=None,
        **kw,  # type: ignore[arg-type]
    )
    return turn


@pytest.mark.anyio
async def test_a_turn_delegates_waits_and_answers_with_the_report(
    pool: Pool, tmp_path: Path
) -> None:
    await AgentStore(pool).all("admin")  # the starters
    project = await ProjectStore(pool).create(owner="admin", name="P", instructions="")
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool, project_id=project.id)

    first = await run.next(calls(("delegate", ASK)))
    offered = {t.name: t for t in first.requests[0].tools}
    assert "delegate" in offered
    assert "Researcher: Reads files" in offered["delegate"].description
    parent = await run.task(turn.id)
    assert parent.state == "waiting" and parent.awaiting_delegation is not None
    assert parent.awaiting_delegation.name == "delegate"
    [child] = await children(pool, turn.id)
    assert child.state == "queued" and child.agent is not None
    assert (child.agent.name, child.delegated_call) == ("Researcher", "call_0")
    assert child.prompt == f"{ASK['task']}\n\nReport back: {ASK['deliverable']}"
    assert child.title.startswith("Researcher: Read notes.md")
    assert (child.workspace, child.project_id, child.model) == (turn.workspace, project.id, "fake")
    assert (child.conversation_id, child.instructions, child.memory) == (None, None, None)
    types = [t for t, _ in await run.events(turn.id)]
    assert types.index("delegation_requested") < types.index("delegated")
    [conv] = await ChatStore(pool).list("admin", limit=10)
    assert conv.last_state == "delegating"  # not "waiting": nobody needs to act

    # The agent's own run: its prompt, its tools only, no further delegation.
    second = await run.next(reply("- Who pays?\n- When?"))
    sent = second.requests[0]
    assert sent.messages[0].content.startswith("You are Researcher, a specialist agent")
    assert "Say where each fact comes from" in sent.messages[0].content
    assert sent.messages[1].content == child.prompt
    assert {t.name for t in sent.tools} == {"list_files", "read_file", "search_knowledge"}
    assert (await run.task(child.id)).state == "completed"
    parent = await run.task(turn.id)
    assert parent.state == "queued" and parent.awaiting_delegation is None
    finished = dict(await run.events(turn.id))["delegation_finished"]
    assert finished == {
        "id": "call_0",
        "task_id": str(child.id),
        "agent": "Researcher",
        "state": "completed",
    }

    third = await run.next(reply("Two questions are open."))
    result = next(m for m in third.requests[0].messages if m.role == "tool")
    assert json.loads(result.content) == {
        "agent": "Researcher",
        "task_id": str(child.id),
        "state": "completed",
        "result": "- Who pays?\n- When?",
    }
    parent = await run.task(turn.id)
    assert (parent.state, parent.result_text) == ("completed", "Two questions are open.")


@pytest.mark.anyio
async def test_an_agent_gets_its_own_model_and_a_copy_of_its_definition(
    pool: Pool, tmp_path: Path
) -> None:
    agents = AgentStore(pool)
    await agents.all("admin")
    coder = await agents.named("admin", "Coder")
    assert coder is not None
    await agents.update(
        coder.id,
        owner="admin",
        name="Coder",
        description=coder.description,
        instructions="",
        model="big-model",
        tools=["write_file"],
    )
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool)
    await run.next(calls(("delegate", {**ASK, "agent": "Coder"})))
    [child] = await children(pool, turn.id)
    assert child.model == "big-model" and child.agent is not None
    await agents.delete("admin", coder.id)  # later changes do not reach the task
    provider = await run.next(reply("done"))
    assert [t.name for t in provider.requests[0].tools] == ["write_file"]  # no project: no search
    assert "Your instructions from the owner" not in provider.requests[0].messages[0].content


@pytest.mark.anyio
async def test_no_such_agent_is_answered_at_once(pool: Pool, tmp_path: Path) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool)
    await run.next(calls(("delegate", {**ASK, "agent": "Nobody"})))
    assert (await run.task(turn.id)).state == "queued"
    assert await children(pool, turn.id) == []
    assert dict(await run.events(turn.id))["delegation_refused"]["id"] == "call_0"
    provider = await run.next(reply("I will do it myself."))
    result = next(m for m in provider.requests[0].messages if m.role == "tool")
    assert json.loads(result.content) == {
        "error": "No agent named 'Nobody'. Agents: Coder, Researcher, Reviewer."
    }

    # Arguments that do not fit the tool are an ordinary tool error: no pause.
    turn = await start_turn(pool)
    provider = await run.next(calls(("delegate", {"agent": "Coder"})), reply("ok"))
    result = next(m for m in provider.requests[1].messages if m.role == "tool")
    assert "invalid_arguments" in result.content
    assert (await run.task(turn.id)).state == "completed"


@pytest.mark.anyio
async def test_a_failed_agent_task_is_reported_and_cannot_be_retried(
    pool: Pool, tmp_path: Path
) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool)
    await run.next(calls(("delegate", ASK)))
    [child] = await children(pool, turn.id)
    await run.next(ProviderError("fake", "auth", "bad key", 401))
    assert (await run.task(child.id)).state == "failed"
    assert await run.tasks.retry(child.id, extra_attempts=1) is None
    provider = await run.next(reply("The researcher failed."))
    result = json.loads(next(m for m in provider.requests[0].messages if m.role == "tool").content)
    assert result["state"] == "failed" and result["error"].startswith("The task failed: auth")


@pytest.mark.anyio
async def test_canceling_the_parent_cancels_its_agents(pool: Pool, tmp_path: Path) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool)
    await run.next(calls(("delegate", ASK)))
    [child] = await children(pool, turn.id)
    canceled = await run.tasks.request_cancel(turn.id)
    assert canceled is not None and canceled.state == "canceled"
    assert canceled.awaiting_delegation is None
    assert (await run.task(child.id)).state == "canceled"
    assert "delegation_finished" not in dict(await run.events(turn.id))  # it stays canceled

    # Canceling only the agent's task hands that back to the parent, which carries on.
    turn = await start_turn(pool)
    await run.next(calls(("delegate", ASK)))
    [child] = await children(pool, turn.id)
    await run.tasks.request_cancel(child.id)
    assert (await run.task(turn.id)).state == "queued"
    provider = await run.next(reply("Canceled, so here is what I know."))
    result = json.loads(next(m for m in provider.requests[0].messages if m.role == "tool").content)
    assert result == {
        "agent": "Researcher",
        "task_id": str(child.id),
        "state": "canceled",
        "error": "The task was canceled.",
    }


@pytest.mark.anyio
async def test_an_agent_task_whose_worker_died_is_reported(
    pool: Pool, tmp_path: Path, db_url: str
) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool)
    await run.next(calls(("delegate", ASK)))
    [child] = await children(pool, turn.id)
    with psycopg.connect(db_url) as conn:  # its last attempt's worker vanished
        conn.execute(
            "UPDATE tasks SET state = 'running', attempt = max_attempts, lease_owner = 'gone', "
            "lease_expires_at = now() - interval '1 minute' WHERE id = %s",
            (child.id,),
        )
    assert await run.tasks.sweep() == 1
    assert (await run.task(turn.id)).state == "queued"
    assert dict(await run.events(turn.id))["delegation_finished"]["state"] == "failed"


@pytest.mark.anyio
async def test_no_agents_no_delegate_tool(pool: Pool, tmp_path: Path) -> None:
    agents = AgentStore(pool)
    for a in await agents.all("admin"):
        await agents.delete("admin", a.id)
    run = Runner(pool, tmp_path)
    await start_turn(pool)
    provider = await run.next(reply("ok"))
    assert "delegate" not in [t.name for t in provider.requests[0].tools]


def ask(agent: str, n: int) -> tuple[str, dict[str, object]]:
    return ("delegate", {"agent": agent, "task": f"Job {n}.", "deliverable": "A line."})


def tool_results(provider: ScriptedProvider, request: int = 0) -> dict[str, dict[str, object]]:
    return {
        str(m.tool_call_id): json.loads(m.content)
        for m in provider.requests[request].messages
        if m.role == "tool"
    }


@pytest.mark.anyio
async def test_one_steps_hand_offs_start_together_and_report_in_any_order(
    pool: Pool, tmp_path: Path
) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool)
    await run.next(calls(ask("Researcher", 0), ask("Coder", 1), ask("Reviewer", 2)))
    kids = await children(pool, turn.id)
    assert [(c.delegated_call, c.state, c.delegation_depth) for c in kids] == [
        ("call_0", "queued", 1),
        ("call_1", "queued", 1),
        ("call_2", "queued", 1),
    ]
    parent = await run.task(turn.id)
    assert parent.state == "waiting" and parent.awaiting_delegation is not None
    assert parent.awaiting_delegation.id == "call_0"
    delegated = [d for t, d in await run.events(turn.id) if t == "delegated"]
    assert [d["agent"] for d in delegated] == ["Researcher", "Coder", "Reviewer"]

    # The second agent ends first: kept for later, the task still waits for the first.
    await run.tasks.request_cancel(kids[1].id)
    parent = await run.task(turn.id)
    assert parent.state == "waiting" and set(parent.delegations) == {"call_1"}
    await run.next(reply("first"))
    assert (await run.task(turn.id)).state == "queued"

    # Resumed, it waits again for the third, which is already working: none start.
    await run.next()
    parent = await run.task(turn.id)
    assert parent.state == "waiting" and parent.awaiting_delegation is not None
    assert parent.awaiting_delegation.id == "call_2"
    assert len(await children(pool, turn.id)) == 3
    await run.next(reply("third"))
    provider = await run.next(reply("All three reported."))
    results = tool_results(provider)
    assert [results[c].get("result") for c in ("call_0", "call_2")] == ["first", "third"]
    assert results["call_1"]["state"] == "canceled"
    assert (await run.task(turn.id)).state == "completed"


@pytest.mark.anyio
async def test_at_most_so_many_agents_work_at_once(pool: Pool, tmp_path: Path) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path, delegation_max_parallel=2)
    turn = await start_turn(pool)
    await run.next(calls(ask("Researcher", 0), ask("Coder", 1), ask("Reviewer", 2)))
    assert [c.delegated_call for c in await children(pool, turn.id)] == ["call_0", "call_1"]
    await run.next(reply("first"))
    await run.next()  # resumes, waits for call_1, and starts call_2 as call_0 is done
    kids = await children(pool, turn.id)
    assert [(c.delegated_call, c.state) for c in kids] == [
        ("call_0", "completed"),
        ("call_1", "queued"),
        ("call_2", "queued"),
    ]
    await run.next(reply("second"))
    assert (await run.task(turn.id)).state == "queued"
    await run.tasks.request_cancel(kids[2].id)  # ends while the parent is queued: kept
    provider = await run.next(reply("done"))
    results = tool_results(provider)
    assert [results[c].get("result") for c in ("call_0", "call_1")] == ["first", "second"]
    assert results["call_2"]["state"] == "canceled"


@pytest.mark.anyio
async def test_hand_offs_past_the_per_task_limit_are_refused(pool: Pool, tmp_path: Path) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path, delegation_max_per_task=2)
    turn = await start_turn(pool)
    await run.next(calls(ask("Nobody", 0), ask("Coder", 1), ask("Reviewer", 2)))
    kids = await children(pool, turn.id)
    assert [c.delegated_call for c in kids] == ["call_1"]  # the refusal counts too
    refused = {
        d["id"]: d["reason"] for t, d in await run.events(turn.id) if t == "delegation_refused"
    }
    assert refused["call_0"].startswith("No agent named 'Nobody'")
    assert refused["call_2"] == "This task already handed out 2 jobs, the most allowed."
    parent = await run.task(turn.id)
    assert parent.awaiting_delegation is None and parent.state == "queued"  # call_0 answered
    await run.next()  # resumes, answers call_0, waits for call_1
    assert (await run.task(turn.id)).state == "waiting"
    await run.next(reply("done"))
    provider = await run.next(reply("ok"))
    results = tool_results(provider)
    assert results["call_2"] == {"error": "This task already handed out 2 jobs, the most allowed."}
    assert results["call_1"]["result"] == "done"
    types = [t for t, _ in await run.events(turn.id)]
    assert types.count("delegation_refused") == 2  # each call is answered once


@pytest.mark.anyio
async def test_agents_hand_on_only_as_deep_as_allowed(pool: Pool, tmp_path: Path) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path, delegation_max_depth=2)
    turn = await start_turn(pool)
    await run.next(calls(ask("Researcher", 0)))
    [child] = await children(pool, turn.id)
    second = await run.next(calls(ask("Coder", 1)))  # the agent may delegate once more
    assert "delegate" in [t.name for t in second.requests[0].tools]
    [grandchild] = await children(pool, child.id)
    assert grandchild.delegation_depth == 2
    third = await run.next(reply("deepest"))
    assert "delegate" not in [t.name for t in third.requests[0].tools]
    assert (await run.task(child.id)).state == "queued"


@pytest.mark.anyio
async def test_a_task_that_ends_cancels_its_working_agents(
    pool: Pool, tmp_path: Path, db_url: str
) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool)
    await run.next(calls(ask("Researcher", 0), ask("Coder", 1)))
    first, second = await children(pool, turn.id)
    await run.next(reply("first"))
    with psycopg.connect(db_url) as conn:  # resumed, its last worker vanished
        conn.execute(
            "UPDATE tasks SET state = 'running', attempt = max_attempts, lease_owner = 'gone', "
            "lease_expires_at = now() - interval '1 minute' WHERE id = %s",
            (turn.id,),
        )
    assert await run.tasks.sweep() == 1
    assert (await run.task(turn.id)).state == "failed"
    assert (await run.task(second.id)).state == "canceled"

    # Retried, the same call ids hand off afresh: the old agent tasks are spent.
    assert await run.tasks.retry(turn.id, extra_attempts=1) is not None
    await run.next(calls(ask("Researcher", 0)))
    kids = await children(pool, turn.id)
    assert len(kids) == 3 and kids[2].state == "queued"
    parent = await run.task(turn.id)
    assert parent.state == "waiting" and parent.awaiting_delegation is not None


@pytest.mark.anyio
async def test_hand_offs_wait_their_turn_behind_an_approval(pool: Pool, tmp_path: Path) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path, approval_required_tools=["delegate"])
    turn = await start_turn(pool)
    await run.next(calls(ask("Researcher", 0), ask("Coder", 1)))
    assert (await run.task(turn.id)).awaiting_approval is not None
    await run.tasks.decide(turn.id, call_id="call_0", approved=True, by="admin")
    await run.next()  # the second call needs its own approval first
    assert [c.delegated_call for c in await children(pool, turn.id)] == ["call_0"]


@pytest.mark.anyio
async def test_calls_past_the_steps_cap_are_not_handed_off(pool: Pool, tmp_path: Path) -> None:
    await AgentStore(pool).all("admin")
    run = Runner(pool, tmp_path, delegation_max_parallel=8)
    turn = await start_turn(pool)
    # The loop runs 8 calls a step; the ninth gets a "limit" error, not an agent.
    await run.next(calls(ask("Nobody", 0), *(ask("Coder", n) for n in range(1, 9))))
    assert len(await children(pool, turn.id)) == 7


def test_a_worker_process_has_a_slot_for_every_agent_the_limit_allows() -> None:
    # A waiting task gives up its slot, but each working agent takes one, and the
    # task resumes in one more: fewer slots than this and the limit cannot be reached.
    s = Settings()
    assert s.worker_concurrency > s.delegation_max_parallel
