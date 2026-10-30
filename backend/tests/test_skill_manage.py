"""skill_manage (D-033): the agent writes skills, and each write waits for the
owner's approval."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from seed_api.agents.store import AgentStore
from seed_api.flow.db import Pool
from seed_api.skills.manage import SkillManageInput
from seed_api.skills.store import SkillStore

from .fakes import calls, reply
from .test_delegation import ASK, Runner, anyio_backend, children, pool, start_turn
from .test_skill_runtime import add

__all__ = ["anyio_backend", "pool"]  # fixtures shared with test_delegation

NEW = {
    "action": "create",
    "name": "Release-Notes",
    "description": "Write  release notes.",
    "tags": ["docs"],
    "instructions": "1. Read the changelog.\n2. Summarize.",
}


def test_a_call_must_say_enough() -> None:
    assert SkillManageInput.model_validate(NEW).name == "release-notes"
    for bad in (
        {**NEW, "name": "two words"},
        {**NEW, "description": None},
        {**NEW, "instructions": None},
        {**NEW, "instructions": "  "},
        {"action": "update", "name": "x"},
        {"action": "rename", "name": "x"},
    ):
        with pytest.raises(ValidationError):
            SkillManageInput.model_validate(bad)
    assert SkillManageInput.model_validate({"action": "delete", "name": "x"}).action == "delete"


async def result(run: Runner) -> dict[str, object]:
    """The last tool result the last run sent the model."""
    sent = run.providers[-1].requests[-1].messages
    return json.loads([m for m in sent if m.role == "tool"][-1].content or "")


@pytest.mark.anyio
async def test_seed_writes_a_shared_skill_once_the_owner_approves(
    pool: Pool, tmp_path: Path
) -> None:
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool, "Remember how to write release notes")
    await run.next(calls(("skill_manage", NEW)))
    waiting = await run.task(turn.id)
    assert waiting.state == "waiting" and waiting.awaiting_approval is not None
    assert waiting.awaiting_approval.name == "skill_manage"
    assert await SkillStore(pool).all("admin") == []  # nothing until approved
    await run.tasks.decide(turn.id, call_id="call_0", approved=True, by="admin")
    await run.next(reply("Saved."))
    assert await result(run) == {"action": "create", "name": "release-notes", "done": True}
    [skill] = await SkillStore(pool).all("admin")
    assert (skill.name, skill.description, skill.tags, skill.agent_id) == (
        "release-notes",
        "Write release notes.",
        ["docs"],
        None,
    )
    assert skill.written_by_task == turn.id

    # A change keeps what it does not name; a refused call changes nothing.
    turn = await start_turn(pool, "Update it")
    change = {"action": "update", "name": "release-notes", "tags": []}
    await run.next(calls(("skill_manage", change)))
    await run.tasks.decide(turn.id, call_id="call_0", approved=True, by="admin")
    await run.next(reply("Changed."))
    [skill] = await SkillStore(pool).all("admin")
    assert (skill.tags, skill.body) == ([], NEW["instructions"])
    turn = await start_turn(pool, "Delete it")
    await run.next(calls(("skill_manage", {"action": "delete", "name": "release-notes"})))
    await run.tasks.decide(turn.id, call_id="call_0", approved=False, by="admin")
    await run.next(reply("Kept."))
    assert (await result(run))["error"] == "denied"
    assert len(await SkillStore(pool).all("admin")) == 1


@pytest.mark.anyio
async def test_bad_calls_are_answered_without_asking(pool: Pool, tmp_path: Path) -> None:
    await add(pool, "taken")
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool, "Save it")
    await run.next(calls(("skill_manage", {**NEW, "instructions": None})), reply("Oops."))
    assert (await result(run))["error"] == "invalid_arguments"
    assert "approval_requested" not in [t for t, _ in await run.events(turn.id)]

    turn = await start_turn(pool, "Save it")
    await run.next(calls(("skill_manage", {**NEW, "name": "taken"})))
    await run.tasks.decide(turn.id, call_id="call_0", approved=True, by="admin")
    await run.next(reply("Taken."))
    assert "exists already" in str((await result(run))["message"])


@pytest.mark.anyio
async def test_an_agent_writes_only_its_own_private_skills(pool: Pool, tmp_path: Path) -> None:
    agents = AgentStore(pool)
    await agents.all("admin")
    researcher = await agents.named("admin", "Researcher")
    coder = await agents.named("admin", "Coder")
    assert researcher is not None and coder is not None
    await add(pool, "shared")
    await add(pool, "coders", agent_id=coder.id)
    await agents.update(  # the owner allows it skill_manage
        researcher.id,
        owner="admin",
        name=researcher.name,
        description=researcher.description,
        instructions=researcher.instructions,
        model=None,
        tools=[*researcher.tools, "skill_manage"],
    )
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool)
    await run.next(calls(("delegate", ASK)))
    [child] = await children(pool, turn.id)
    await run.next(
        calls(("skill_manage", NEW), ("skill_manage", {"action": "delete", "name": "shared"}))
    )
    await run.tasks.decide(child.id, call_id="call_0", approved=True, by="admin")
    await run.next()  # the second call waits for its own approval
    await run.tasks.decide(child.id, call_id="call_1", approved=True, by="admin")
    # Approved or not, another's skill is not this agent's to change.
    await run.next(reply("Done."))
    assert "no skill called shared that you may change" in str((await result(run))["message"])
    names = {s.name: s.agent_id for s in await SkillStore(pool).all("admin")}
    assert names == {"coders": coder.id, "release-notes": researcher.id, "shared": None}
