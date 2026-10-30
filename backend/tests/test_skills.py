"""Skills (D-033): the owner's saved procedures, written here or imported from a
Hermes Agent SKILL.md."""

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from seed_api.config import Settings
from seed_api.skills.skillmd import SkillMdError, parse

from .conftest import sign_in, start

DEPLOY = {
    "name": " Deploy-Site ",
    "description": "Ship the site  to the VPS.",
    "tags": ["ops", " ops ", "", "web  deploy"],
    "body": "  1. Build.\n2. Push.  ",
}

HERMES = """﻿---
name: deploy-k8s
description: Deploy an app to Kubernetes
version: 1.0.0
platforms: [linux]
requires_toolsets: [terminal]
metadata:
  hermes:
    tags: [devops, kubernetes]
    category: devops
---
# Deploy to Kubernetes

## When to Use
When the user asks to deploy.
"""


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings) as c:
        yield sign_in(c)


def test_parse_reads_a_hermes_skill_md() -> None:
    md = parse(HERMES.replace("\n", "\r\n"))
    assert (md.name, md.description, md.tags) == (
        "deploy-k8s",
        "Deploy an app to Kubernetes",
        ["devops", "kubernetes"],
    )
    assert md.body == "# Deploy to Kubernetes\n\n## When to Use\nWhen the user asks to deploy."
    assert md.ignored == ["metadata.hermes.category", "platforms", "requires_toolsets", "version"]
    # Top-level tags win, and the shorthand `a, b` is a list.
    md = parse(
        "---\nname: a\ndescription: b\ntags: x, y\nmetadata:\n  hermes:\n    tags: [z]\n---\nDo it."
    )
    assert (md.tags, md.ignored) == (["x", " y"], ["metadata.hermes.tags"])


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("name: a\n---\nbody", "starts with a YAML header"),
        ("---\nname: a\nbody", "no closing ---"),
        ("---\nname: a\ndescription: [unclosed\n---\nbody", "could not be read on line 3"),
        ("---\n- a\n- b\n---\nbody", "key: value"),
        ("---\nname: a\ntags: 3\n---\nbody", "tags must be a list"),
        ("---\n" + "x" * 40_000 + "\n---\n", "at most 40000"),
    ],
)
def test_parse_says_what_is_wrong(text: str, message: str) -> None:
    with pytest.raises(SkillMdError, match=message):
        parse(text)


def test_write_list_change_and_delete_skills(api: TestClient, db_url: str) -> None:
    assert api.get("/api/v1/skills").json() == []
    r = api.post("/api/v1/skills", json=DEPLOY)
    assert r.status_code == 201, r.text
    s = r.json()
    assert (s["name"], s["description"], s["tags"], s["body"], s["agent_id"]) == (
        "deploy-site",
        "Ship the site to the VPS.",
        ["ops", "web deploy"],
        "1. Build.\n2. Push.",
        None,
    )
    other = {**DEPLOY, "name": "audit"}
    assert api.post("/api/v1/skills", json=other).status_code == 201
    assert [x["name"] for x in api.get("/api/v1/skills").json()] == ["audit", "deploy-site"]

    taken = api.post("/api/v1/skills", json={**DEPLOY, "name": "DEPLOY-SITE"})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "name_taken"
    for bad in (
        {**DEPLOY, "name": "deploy site"},
        {**DEPLOY, "name": "-deploy"},
        {**DEPLOY, "name": "x" * 65},
        {**DEPLOY, "name": "a/b"},
        {**DEPLOY, "description": "  "},
        {**DEPLOY, "description": "d" * 1025},
        {**DEPLOY, "tags": [f"t{i}" for i in range(21)]},
        {**DEPLOY, "tags": ["t" * 41]},
        {**DEPLOY, "body": "   "},
        {**DEPLOY, "body": "b" * 20_001},
    ):
        assert api.post("/api/v1/skills", json=bad).status_code == 422, bad

    url = f"/api/v1/skills/{s['id']}"
    assert api.get(url).json()["name"] == "deploy-site"
    changed = api.put(url, json={**DEPLOY, "name": "ship", "tags": []})
    assert changed.status_code == 200
    assert (changed.json()["name"], changed.json()["tags"]) == ("ship", [])
    assert api.put(url, json=other).status_code == 409  # audit is taken
    assert api.get(url).json()["name"] == "ship"

    missing = f"/api/v1/skills/{uuid.uuid4()}"
    assert api.get(missing).status_code == 404
    assert api.put(missing, json=DEPLOY).status_code == 404
    assert api.delete(missing).status_code == 404
    assert api.delete(url).status_code == 204
    assert api.get(url).status_code == 404

    with psycopg.connect(db_url) as conn:
        audit = conn.execute(
            "SELECT action, target, detail FROM audit_log WHERE action LIKE 'skill_%' ORDER BY id"
        ).fetchall()
    assert [(act, t) for act, t, _ in audit] == [
        ("skill_created", s["id"]),
        ("skill_created", audit[1][1]),
        ("skill_updated", s["id"]),
        ("skill_deleted", s["id"]),
    ]
    assert audit[2][2] == {"name": "ship", "agent_id": None}


def test_a_skill_can_be_private_to_an_agent(api: TestClient, db_url: str) -> None:
    agent = next(a for a in api.get("/api/v1/agents").json() if a["name"] == "Coder")
    theirs = uuid.uuid4()
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO agents (id, owner, name, description) VALUES (%s, 'other', 'X', 'X.')",
            (theirs,),
        )
    r = api.post("/api/v1/skills", json={**DEPLOY, "agent_id": agent["id"]})
    assert r.status_code == 201 and r.json()["agent_id"] == agent["id"]
    url = f"/api/v1/skills/{r.json()['id']}"
    for agent_id in (str(theirs), str(uuid.uuid4())):  # not the owner's agent
        bad = {**DEPLOY, "name": "x", "agent_id": agent_id}
        assert api.post("/api/v1/skills", json=bad).json()["error"]["code"] == "no_such_agent"
        assert api.put(url, json=bad).status_code == 422
    assert api.put(url, json={**DEPLOY, "agent_id": None}).json()["agent_id"] is None
    assert api.put(url, json={**DEPLOY, "agent_id": agent["id"]}).status_code == 200
    # Deleting the agent deletes its private skills.
    assert api.delete(f"/api/v1/agents/{agent['id']}").status_code == 204
    assert api.get(url).status_code == 404


def test_import_a_hermes_skill_md(api: TestClient) -> None:
    r = api.post("/api/v1/skills/import", json={"text": HERMES})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ignored"] == [
        "metadata.hermes.category",
        "platforms",
        "requires_toolsets",
        "version",
    ]
    assert (body["skill"]["name"], body["skill"]["tags"]) == (
        "deploy-k8s",
        ["devops", "kubernetes"],
    )
    assert body["skill"]["body"].startswith("# Deploy to Kubernetes")
    assert api.get(f"/api/v1/skills/{body['skill']['id']}").json() == body["skill"]

    again = api.post("/api/v1/skills/import", json={"text": HERMES})
    assert again.status_code == 409
    for text, message in (
        ("no header", "starts with a YAML header"),
        ("---\ndescription: d\n---\nbody", "name: Input should be a valid string"),
        ("---\nname: Has Space\ndescription: d\n---\nbody", "name: Use 1-64 lower-case"),
        ("---\nname: ok\ndescription: d\n---\n", "body: Write the skill's instructions."),
    ):
        r = api.post("/api/v1/skills/import", json={"text": text})
        assert r.status_code == 422, text
        assert r.json()["error"]["code"] == "invalid_skill_md"
        assert message in r.json()["error"]["message"], r.json()
    no_agent = {"text": HERMES.replace("deploy-k8s", "k8s"), "agent_id": str(uuid.uuid4())}
    assert api.post("/api/v1/skills/import", json=no_agent).status_code == 422


def test_skills_belong_to_their_owner(api: TestClient, db_url: str) -> None:
    theirs = uuid.uuid4()
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO skills (id, owner, name, description, body) "
            "VALUES (%s, 'other', 'deploy-site', 'Theirs.', 'x')",
            (theirs,),
        )
    assert api.get("/api/v1/skills").json() == []
    url = f"/api/v1/skills/{theirs}"
    assert api.get(url).status_code == 404
    assert api.put(url, json=DEPLOY).status_code == 404
    assert api.delete(url).status_code == 404
    assert api.post("/api/v1/skills", json=DEPLOY).status_code == 201  # names are per owner


def test_skills_need_a_signed_in_admin(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/skills").status_code == 401
        assert c.post("/api/v1/skills", json=DEPLOY).status_code in (401, 403)
        assert c.post("/api/v1/skills/import", json={"text": HERMES}).status_code in (401, 403)
