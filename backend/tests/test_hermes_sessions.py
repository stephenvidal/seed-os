"""Past Hermes Agent sessions as SEED chats (D-045)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from seed_api.chat.hermes import HermesMessage, turns_of
from seed_api.config import Settings

from .conftest import sign_in, start


def msg(role: str, content: str, at: float) -> HermesMessage:
    return HermesMessage(role=role, content=content, timestamp=at)  # type: ignore[arg-type]


def test_turns_pair_each_question_with_the_text_that_followed() -> None:
    turns = turns_of(
        [
            msg("assistant", "Hello, I'm Hermes.", 1),  # before any question: left out
            msg("user", "Where is the backup?", 2),
            msg("assistant", "", 3),  # a tool-call step with no text
            msg("assistant", "On the NAS,", 4),
            msg("assistant", "in /backups.", 5),
            msg("user", "  ", 6),  # blank: no turn
            msg("user", "Thanks", 8),
            msg("user", "Bye", 7),  # out of order in the file: sorted by time
        ]
    )
    assert [(t.prompt, t.answer) for t in turns] == [
        ("Where is the backup?", "On the NAS,\n\nin /backups."),
        ("Bye", ""),
        ("Thanks", ""),
    ]
    assert (turns[0].asked_at, turns[0].answered_at) == (2, 5)


@pytest.fixture
def api(db_settings: Settings) -> Iterator[TestClient]:
    with start(db_settings) as c:
        yield sign_in(c)


SESSION = {
    "id": "20260301_101500_abc",
    "title": "Backup plan",
    "source": "telegram",
    "model": "hermes-3",
    "started_at": 1772360100.0,  # 2026-03-01
    "messages": [
        {
            "role": "user",
            "content": "Where should the zebrafish backups go?",
            "timestamp": 1772360100.0,
        },
        {"role": "assistant", "content": "Put them on the NAS.", "timestamp": 1772360110.0},
        {"role": "user", "content": "How often?", "timestamp": 1772360200.0},
        {"role": "assistant", "content": "Nightly at 02:00.", "timestamp": 1772360210.0},
    ],
}


def test_sessions_become_finished_chats_once_and_are_found_by_search(
    api: TestClient, db_url: str
) -> None:
    empty = {**SESSION, "id": "s-empty", "messages": [SESSION["messages"][1]]}
    r = api.post("/api/v1/conversations/import-hermes", json={"sessions": [SESSION, empty]})
    assert r.status_code == 200, r.text
    first, skipped = r.json()
    assert (first["outcome"], first["turns"]) == ("imported", 2)
    assert (skipped["outcome"], skipped["conversation_id"]) == ("empty", None)

    [conv] = api.get("/api/v1/conversations").json()
    assert (conv["title"], conv["model"], conv["turns"], conv["last_state"]) == (
        "Backup plan",
        "hermes-3",
        2,
        "completed",
    )
    assert conv["created_at"].startswith("2026-03-01")
    detail = api.get(f"/api/v1/conversations/{conv['id']}").json()
    tasks = detail["turns"]
    assert [(t["prompt"], t["result_text"]) for t in tasks] == [
        ("Where should the zebrafish backups go?", "Put them on the NAS."),
        ("How often?", "Nightly at 02:00."),
    ]
    assert {t["state"] for t in tasks} == {"completed"}

    again = api.post("/api/v1/conversations/import-hermes", json={"sessions": [SESSION]})
    assert again.json()[0]["outcome"] == "already_imported"
    assert len(api.get("/api/v1/conversations").json()) == 1

    # Past-chat search (D-039) finds what was said in Hermes.
    import asyncio

    from seed_api.chat.recall import RecallStore
    from seed_api.flow.db import make_pool

    async def search() -> list[str]:
        pool = make_pool(db_url, max_size=1)
        await pool.open(wait=True)
        try:
            hits = await RecallStore(pool).search("admin", "zebrafish backups")
            return [h.asked for h in hits]
        finally:
            await pool.close()

    assert asyncio.run(search()) == ["Where should the zebrafish backups go?"]


def test_bad_batches_are_refused(api: TestClient) -> None:
    url = "/api/v1/conversations/import-hermes"
    assert api.post(url, json={"sessions": []}).status_code == 422
    bad_role = {**SESSION, "messages": [{"role": "tool", "content": "x", "timestamp": 1.0}]}
    assert api.post(url, json={"sessions": [bad_role]}).status_code == 422
    assert api.post(url, json={"sessions": [SESSION] * 51}).status_code == 422
