"""Skills in tasks (D-033): the prompt's index, skill_list and skill_view, the skills
each agent may use, and the `/name` prefix that makes a turn follow one."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seed_api.agents.store import AgentStore
from seed_api.config import Settings
from seed_api.flow.db import Pool
from seed_api.skills.runtime import INDEX_LIMIT, forced_skill, skill_tools, skills_index
from seed_api.skills.store import Skill, SkillStore

from .conftest import sign_in, start
from .fakes import calls, reply
from .test_delegation import ASK, Runner, anyio_backend, children, pool, start_turn

__all__ = ["anyio_backend", "pool"]  # fixtures shared with test_delegation


def skill(name: str, body: str = "Do it.") -> Skill:
    now = datetime.now(UTC)
    return Skill(
        id=uuid.uuid4(),
        owner="admin",
        agent_id=None,
        name=name,
        description=f"For {name}.",
        tags=["t"],
        body=body,
        written_by_task=None,
        created_at=now,
        updated_at=now,
    )


def test_the_index_lists_names_and_descriptions_never_bodies() -> None:
    text = skills_index([skill("deploy", "SECRET STEPS"), skill("audit")])
    assert "- deploy: For deploy.\n- audit: For audit." in text
    assert "SECRET STEPS" not in text and "more:" not in text
    many = skills_index([skill(f"s{i}") for i in range(INDEX_LIMIT + 3)])
    assert many.count("\n- ") == INDEX_LIMIT
    assert many.endswith("(3 more: use skill_list to see them all.)")


def test_forced_skill_reads_a_leading_slash_name() -> None:
    deploy = skill("deploy-site")
    assert forced_skill("/Deploy-Site ship it", [deploy]).skill == deploy  # type: ignore[union-attr]
    assert forced_skill("/deploy-site", [deploy]).skill == deploy  # type: ignore[union-attr]
    missing = forced_skill("  /nope do it", [deploy])
    assert missing is not None and (missing.name, missing.skill) == ("nope", None)
    for prompt in ("deploy-site please", "/etc/hosts is wrong", "a /deploy-site b", "/"):
        assert forced_skill(prompt, [deploy]) is None, prompt


@pytest.mark.anyio
async def test_skill_view_reads_from_the_tasks_copy() -> None:
    listing, view = skill_tools([skill("deploy", "1. Build.")])
    out = await listing.handler(listing.input_model())
    assert out.model_dump() == {
        "skills": [{"name": "deploy", "description": "For deploy.", "tags": ["t"]}]
    }
    got = await view.handler(view.input_model(name=" Deploy "))
    assert got.model_dump()["instructions"] == "1. Build."
    with pytest.raises(Exception, match="No skill named 'x'. Skills: deploy."):
        await view.handler(view.input_model(name="x"))


async def add(pool: Pool, name: str, agent_id: uuid.UUID | None = None, body: str = "") -> Skill:
    return await SkillStore(pool).create(
        owner="admin",
        agent_id=agent_id,
        name=name,
        description=f"For {name}.",
        tags=[],
        body=body or f"Steps for {name}.",
    )


@pytest.mark.anyio
async def test_a_turn_sees_the_shared_skills_and_reads_one(pool: Pool, tmp_path: Path) -> None:
    agents = AgentStore(pool)
    await agents.all("admin")
    coder = await agents.named("admin", "Coder")
    assert coder is not None
    await add(pool, "deploy", body="1. Build.\n2. Push.")
    await add(pool, "coder-only", agent_id=coder.id)
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool, "Ship the site")
    provider = await run.next(calls(("skill_view", {"name": "deploy"})), reply("Shipped."))
    first = provider.requests[0]
    system = first.messages[0].content or ""
    assert "Skills: procedures the owner saved" in system
    assert "- deploy: For deploy." in system
    assert "coder-only" not in system  # private to Coder
    assert "1. Build." not in system  # only the index, until it is read
    assert {"skill_list", "skill_view"} <= {t.name for t in first.tools}
    result = next(m for m in provider.requests[1].messages if m.role == "tool")
    assert json.loads(result.content or "")["instructions"] == "1. Build.\n2. Push."
    assert (await run.task(turn.id)).state == "completed"
    assert "skill_forced" not in [t for t, _ in await run.events(turn.id)]


@pytest.mark.anyio
async def test_no_skills_no_skill_tools(pool: Pool, tmp_path: Path) -> None:
    run = Runner(pool, tmp_path)
    await start_turn(pool, "Hi")
    provider = await run.next(reply("Hello."))
    assert not {"skill_list", "skill_view"} & {t.name for t in provider.requests[0].tools}
    assert "Skills:" not in (provider.requests[0].messages[0].content or "")


@pytest.mark.anyio
async def test_a_slash_name_turn_follows_that_skill(pool: Pool, tmp_path: Path) -> None:
    await add(pool, "deploy", body="1. Build.\n2. Push.")
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool, "/deploy the blog")
    provider = await run.next(reply("Done."))
    sent = provider.requests[0].messages
    assert "use the skill deploy for this message. Follow it:\n1. Build.\n2. Push." in (
        sent[0].content or ""
    )
    assert sent[-1].content == "/deploy the blog"  # the message stays as the owner wrote it
    assert ("skill_forced", {"name": "deploy", "found": True}) in await run.events(turn.id)

    other = await start_turn(pool, "/deploy-k8s now")
    provider = await run.next(reply("No such skill."))
    assert "starts with /deploy-k8s. You have no skill by that name" in (
        provider.requests[0].messages[0].content or ""
    )
    assert ("skill_forced", {"name": "deploy-k8s", "found": False}) in await run.events(other.id)


@pytest.mark.anyio
async def test_an_agent_sees_its_allowed_and_private_skills(pool: Pool, tmp_path: Path) -> None:
    agents = AgentStore(pool)
    await agents.all("admin")
    researcher = await agents.named("admin", "Researcher")
    coder = await agents.named("admin", "Coder")
    assert researcher is not None and coder is not None
    allowed = await add(pool, "cite")
    await add(pool, "unallowed")
    await add(pool, "mine", agent_id=researcher.id)
    await add(pool, "coders", agent_id=coder.id)
    await agents.update(
        researcher.id,
        owner="admin",
        name=researcher.name,
        description=researcher.description,
        instructions=researcher.instructions,
        model=None,
        tools=researcher.tools,
        skills=[allowed.id],
    )
    run = Runner(pool, tmp_path)
    turn = await start_turn(pool, "/mine look")  # SEED cannot use an agent's private skill
    # A delegated task that starts with a slash is SEED's text, not the owner's /name.
    parent = await run.next(calls(("delegate", {**ASK, "task": "/cite the sources"})))
    assert "You have no skill by that name" in (parent.requests[0].messages[0].content or "")
    [child] = await children(pool, turn.id)
    agent = await run.next(reply("Report."))
    system = agent.requests[0].messages[0].content or ""
    assert system.startswith("You are Researcher") and "use the skill" not in system
    lines = [ln for ln in system.splitlines() if ln.startswith("- ")]
    assert lines == ["- cite: For cite.", "- mine: For mine."]
    assert {"skill_list", "skill_view"} <= {t.name for t in agent.requests[0].tools}
    assert "skill_forced" not in [t for t, _ in await run.events(child.id)]


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings) as c:
        yield sign_in(c)


def test_an_agent_may_be_allowed_only_its_owners_shared_skills(api: TestClient) -> None:
    agents = {a["name"]: a for a in api.get("/api/v1/agents").json()}
    coder = agents["Coder"]
    body = {"description": "For it.", "body": "Steps."}
    shared = api.post("/api/v1/skills", json={**body, "name": "shared"}).json()
    private = api.post(
        "/api/v1/skills", json={**body, "name": "private", "agent_id": coder["id"]}
    ).json()
    definition = {k: coder[k] for k in ("name", "description", "instructions", "model", "tools")}
    url = f"/api/v1/agents/{coder['id']}"
    for bad in ([private["id"]], [str(uuid.uuid4())]):
        r = api.put(url, json={**definition, "skills": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "no_such_skill"
        r = api.post("/api/v1/agents", json={**definition, "name": "New", "skills": bad})
        assert r.status_code == 422
    r = api.put(url, json={**definition, "skills": [shared["id"], shared["id"]]})
    assert r.status_code == 200 and r.json()["skills"] == [shared["id"]]
    assert api.get(url).json()["skills"] == [shared["id"]]
    assert api.put(url, json=definition).json()["skills"] == [shared["id"]]  # left out: kept

    # A skill that stops being shared, or is deleted, leaves the agents' lists.
    again = {**body, "name": "shared", "agent_id": agents["Reviewer"]["id"]}
    assert api.put(f"/api/v1/skills/{shared['id']}", json=again).status_code == 200
    assert api.get(url).json()["skills"] == []
    assert api.put(f"/api/v1/skills/{shared['id']}", json={**body, "name": "shared"}).is_success
    assert api.put(url, json={**definition, "skills": [shared["id"]]}).status_code == 200
    assert api.delete(f"/api/v1/skills/{shared['id']}").status_code == 204
    assert api.get(url).json()["skills"] == []
