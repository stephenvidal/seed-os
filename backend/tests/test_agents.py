"""Agent definitions (D-024): the specialists the assistant can delegate to."""

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from seed_api.config import Settings

from .conftest import sign_in, start

RESEARCHER = {
    "name": "Analyst",
    "description": "Finds and reads sources;  reports what they say.",
    "instructions": "  Cite every source.  ",
    "model": "  ",
    "tools": ["read_file", "search_knowledge", "list_files", "read_file"],
}


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings.model_copy(update={"ollama_api_key": SecretStr("unused")})) as c:
        yield sign_in(c)


def test_starters_are_given_once(api: TestClient, db_url: str) -> None:
    with psycopg.connect(db_url) as conn:  # an agent of theirs named like a starter stays
        conn.execute(
            "INSERT INTO agents (id, owner, name, description) "
            "VALUES (%s, 'admin', 'coder', 'Mine.')",
            (uuid.uuid4(),),
        )
    first = api.get("/api/v1/agents").json()
    assert [(a["name"], a["tools"]) for a in first] == [
        ("coder", []),
        ("Researcher", ["list_files", "read_file", "search_knowledge"]),
        ("Reviewer", ["list_files", "read_file"]),
    ]
    assert all(a["model"] is None for a in first)
    assert "Do not change files." in first[1]["instructions"]
    assert api.get("/api/v1/agents").json() == first  # not added twice
    for a in first:
        assert api.delete(f"/api/v1/agents/{a['id']}").status_code == 204
    assert api.get("/api/v1/agents").json() == []  # deleted starters stay deleted


def test_define_list_change_and_delete_agents(api: TestClient, db_url: str) -> None:
    starters = {a["name"] for a in api.get("/api/v1/agents").json()}
    assert starters == {"Researcher", "Coder", "Reviewer"}
    r = api.post("/api/v1/agents", json=RESEARCHER)
    assert r.status_code == 201
    a = r.json()
    assert (a["name"], a["description"], a["instructions"], a["model"], a["tools"]) == (
        "Analyst",
        "Finds and reads sources; reports what they say.",
        "Cite every source.",
        None,  # blank: the delegating task's model
        ["list_files", "read_file", "search_knowledge"],  # once each, catalog order
    )
    builder = {"name": "builder", "description": "Builds.", "model": "m-big", "tools": []}
    assert api.post("/api/v1/agents", json=builder).status_code == 201
    names = [x["name"] for x in api.get("/api/v1/agents").json()]
    assert names == ["Analyst", "builder", "Coder", "Researcher", "Reviewer"]  # by name, any case

    taken = api.post("/api/v1/agents", json={**RESEARCHER, "name": "analyst"})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "name_taken"
    for bad in (
        {**RESEARCHER, "name": " "},
        {**RESEARCHER, "name": "-dash"},
        {**RESEARCHER, "name": "x" * 41},
        {**RESEARCHER, "name": "a/b"},
        {**RESEARCHER, "description": "  "},
        {**RESEARCHER, "description": "d" * 501},
        {**RESEARCHER, "tools": ["remember"]},
        {**RESEARCHER, "tools": ["rm_rf"]},
        {**RESEARCHER, "instructions": "i" * 20_001},
    ):
        assert api.post("/api/v1/agents", json=bad).status_code == 422, bad

    url = f"/api/v1/agents/{a['id']}"
    assert api.get(url).json()["name"] == "Analyst"
    changed = api.put(url, json={**RESEARCHER, "name": "Scout", "tools": ["run_command"]})
    assert changed.status_code == 200
    assert (changed.json()["name"], changed.json()["tools"]) == ("Scout", ["run_command"])
    assert api.put(url, json={**builder}).status_code == 409  # builder is taken
    assert api.get(url).json()["name"] == "Scout"

    missing = f"/api/v1/agents/{uuid.uuid4()}"
    assert api.get(missing).status_code == 404
    assert api.put(missing, json=RESEARCHER).status_code == 404
    assert api.delete(missing).status_code == 404
    assert api.delete(url).status_code == 204
    assert api.get(url).status_code == 404
    assert "Scout" not in [x["name"] for x in api.get("/api/v1/agents").json()]

    with psycopg.connect(db_url) as conn:
        audit = conn.execute(
            "SELECT action, target, detail FROM audit_log WHERE action LIKE 'agent_%' ORDER BY id"
        ).fetchall()
    assert [(act, t) for act, t, _ in audit] == [
        ("agent_created", a["id"]),
        ("agent_created", audit[1][1]),
        ("agent_updated", a["id"]),
        ("agent_deleted", a["id"]),
    ]
    assert audit[2][2] == {"name": "Scout", "tools": ["run_command"]}


def test_agents_belong_to_their_owner(api: TestClient, db_url: str) -> None:
    theirs = uuid.uuid4()
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO agents (id, owner, name, description) "
            "VALUES (%s, 'other', 'Analyst', 'Theirs.')",
            (theirs,),
        )
    assert str(theirs) not in {a["id"] for a in api.get("/api/v1/agents").json()}
    url = f"/api/v1/agents/{theirs}"
    assert api.get(url).status_code == 404
    assert api.put(url, json=RESEARCHER).status_code == 404
    assert api.delete(url).status_code == 404
    # Names are unique per owner: the same name is free here.
    assert api.post("/api/v1/agents", json=RESEARCHER).status_code == 201


def test_agents_need_a_signed_in_admin(db_settings: Settings) -> None:
    with start(db_settings) as c:
        assert c.get("/api/v1/agents").status_code == 401
        assert c.post("/api/v1/agents", json=RESEARCHER).status_code in (401, 403)
