"""Artifacts (ADR-0014) over a real Postgres: every changed file is saved after a
run, with versions, and a wiped workspace is refilled from what was saved."""

import base64
import hashlib
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from seed_api.chat.store import ChatStore
from seed_api.config import Settings
from seed_api.flow.db import Pool, make_pool, migrate
from seed_api.flow.store import TaskStore
from seed_api.flow.worker import Worker
from seed_api.sandbox.client import SandboxClient
from seed_api.sandbox.server import create_sandbox_app
from seed_api.studio import files as studio_files
from seed_api.studio.capture import save_changes
from seed_api.studio.store import ArtifactStore
from seed_api.studio.workspace import LocalFiles, SandboxFiles

from .fakes import ScriptedProvider, Step, calls, reply

pytestmark = pytest.mark.anyio
sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731


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


@pytest.fixture
def tasks(pool: Pool) -> TaskStore:
    return TaskStore(pool)


@pytest.fixture
def artifacts(pool: Pool, tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(pool, tmp_path / "artifacts")


@pytest.fixture
def wsettings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=str(tmp_path / "ws"), worker_lease_seconds=3)


async def run(
    tasks: TaskStore, settings: Settings, artifacts: ArtifactStore | None, script: list[Step]
) -> ScriptedProvider:
    provider = ScriptedProvider(script)
    w = Worker(tasks, settings, lambda: provider, artifacts=artifacts, worker_id="w")
    assert await w.run_once()
    return provider


async def events(tasks: TaskStore, task_id: uuid.UUID, type_: str) -> list[dict[str, object]]:
    return [e.data for e in await tasks.events(task_id, after=0, limit=200) if e.type == type_]


async def versions(pool: Pool, workspace: uuid.UUID) -> list[tuple[str, int, str | None]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT a.path, v.version, v.sha256 FROM artifacts a "
            "JOIN artifact_versions v ON v.artifact_id = a.id "
            "WHERE a.workspace_id = %s ORDER BY a.path, v.version",
            (workspace,),
        )
        return [(r["path"], r["version"], r["sha256"]) for r in await cur.fetchall()]


async def test_a_run_saves_the_files_it_made(
    tasks: TaskStore, artifacts: ArtifactStore, wsettings: Settings, pool: Pool
) -> None:
    task, _ = await tasks.create(
        created_by="admin",
        title="t",
        model="fake",
        prompt="p",
        max_attempts=3,
        idempotency_key=None,
    )
    await run(
        tasks,
        wsettings,
        artifacts,
        [
            calls(
                ("write_file", {"path": "site/index.html", "content": "<h1>hi</h1>"}),
                ("write_file", {"path": "notes.txt", "content": "n"}),
            ),
            reply("done"),
        ],
    )
    done = await tasks.get(task.id)
    assert done is not None and done.state == "completed"
    [report] = await events(tasks, task.id, "artifacts_saved")
    assert report == {
        "saved": [
            {"path": "notes.txt", "version": 1, "deleted": False},
            {"path": "site/index.html", "version": 1, "deleted": False},
        ],
        "skipped": [],
        "truncated": False,
    }
    assert await versions(pool, task.id) == [
        ("notes.txt", 1, sha(b"n")),
        ("site/index.html", 1, sha(b"<h1>hi</h1>")),
    ]
    # The content is on disk under its hash, written whole.
    for content in (b"<h1>hi</h1>", b"n"):
        h = sha(content)
        assert (artifacts.root / "blobs" / h[:2] / h).read_bytes() == content
    types = [e.type for e in await tasks.events(task.id, after=0, limit=200)]
    assert types.index("artifacts_saved") > types.index("run_finished")


async def test_later_turns_add_versions_only_for_what_changed(
    pool: Pool, tasks: TaskStore, artifacts: ArtifactStore, wsettings: Settings, tmp_path: Path
) -> None:
    chat = ChatStore(pool)
    conv, first, _ = await chat.start(
        owner="admin", model="fake", prompt="make files", max_attempts=3, idempotency_key=None
    )
    await run(
        tasks,
        wsettings,
        artifacts,
        [
            calls(
                ("write_file", {"path": "a.txt", "content": "one"}),
                ("write_file", {"path": "b.txt", "content": "keep"}),
                ("write_file", {"path": "c.txt", "content": "bye"}),
            ),
            reply("made"),
        ],
    )
    (tmp_path / "ws" / str(conv.id) / "c.txt").unlink()  # as `rm c.txt` would
    second, _ = await chat.send(
        conv.id,
        owner="admin",
        prompt="change a",
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=20,
    )
    await run(
        tasks,
        wsettings,
        artifacts,
        [calls(("write_file", {"path": "a.txt", "content": "two"})), reply("changed")],
    )
    [report] = await events(tasks, second.id, "artifacts_saved")
    assert report["saved"] == [
        {"path": "a.txt", "version": 2, "deleted": False},
        {"path": "c.txt", "version": 2, "deleted": True},
    ]
    assert await versions(pool, conv.id) == [
        ("a.txt", 1, sha(b"one")),
        ("a.txt", 2, sha(b"two")),
        ("b.txt", 1, sha(b"keep")),
        ("c.txt", 1, sha(b"bye")),
        ("c.txt", 2, None),
    ]
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT a.conversation_id, v.task_id FROM artifacts a "
            "JOIN artifact_versions v ON v.artifact_id = a.id "
            "WHERE a.workspace_id = %s AND a.path = 'a.txt' ORDER BY v.version",
            (conv.id,),
        )
        assert [(r["conversation_id"], r["task_id"]) for r in await cur.fetchall()] == [
            (conv.id, first.id),
            (conv.id, second.id),
        ]
    # A run that changes nothing saves nothing and logs nothing.
    third, _ = await chat.send(
        conv.id,
        owner="admin",
        prompt="anything?",
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=20,
    )
    await run(tasks, wsettings, artifacts, [reply("no")])
    assert await events(tasks, third.id, "artifacts_saved") == []

    # Deleting the conversation deletes its artifacts.
    assert await chat.delete(conv.id, owner="admin") == 3
    assert await versions(pool, conv.id) == []


async def test_a_wiped_workspace_is_refilled_before_the_next_turn(
    pool: Pool, tasks: TaskStore, artifacts: ArtifactStore, wsettings: Settings, tmp_path: Path
) -> None:
    chat = ChatStore(pool)
    conv, _, _ = await chat.start(
        owner="admin", model="fake", prompt="make", max_attempts=3, idempotency_key=None
    )
    await run(
        tasks,
        wsettings,
        artifacts,
        [
            calls(
                ("write_file", {"path": "app/main.py", "content": "print(1)"}),
                ("write_file", {"path": "gone.txt", "content": "x"}),
            ),
            reply("made"),
        ],
    )
    (tmp_path / "ws" / str(conv.id) / "gone.txt").unlink()
    await chat.send(
        conv.id,
        owner="admin",
        prompt="note",
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=20,
    )
    await run(tasks, wsettings, artifacts, [reply("ok")])  # records gone.txt as deleted
    shutil.rmtree(tmp_path / "ws" / str(conv.id))  # the sandbox restarted
    third, _ = await chat.send(
        conv.id,
        owner="admin",
        prompt="read it",
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=20,
    )
    provider = await run(
        tasks,
        wsettings,
        artifacts,
        [calls(("read_file", {"path": "app/main.py"})), reply("print(1)")],
    )
    assert await events(tasks, third.id, "workspace_restored") == [{"files": 1}]
    tool_msg = next(m for m in provider.requests[1].messages if m.role == "tool")
    assert "print(1)" in tool_msg.content
    ws = tmp_path / "ws" / str(conv.id)
    assert sorted(p.name for p in ws.rglob("*") if p.is_file()) == ["main.py"]  # not gone.txt
    # Nothing changed, so the restore itself adds no versions.
    assert await events(tasks, third.id, "artifacts_saved") == []
    # A workspace that still has files is left as it is.
    fourth, _ = await chat.send(
        conv.id,
        owner="admin",
        prompt="again",
        model=None,
        max_attempts=3,
        idempotency_key=None,
        context_turns=20,
    )
    await run(tasks, wsettings, artifacts, [reply("ok")])
    assert await events(tasks, fourth.id, "workspace_restored") == []


async def test_large_files_are_skipped_and_a_cut_off_listing_records_no_deletions(
    pool: Pool,
    artifacts: ArtifactStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = uuid.uuid4()
    root = tmp_path / "local"
    files = LocalFiles(root)
    (root / "big.bin").write_bytes(b"\0" * (studio_files.MAX_ARTIFACT_BYTES + 1))
    (root / "a.txt").write_text("a")
    (root / "b.txt").write_text("b")
    (root / "link").symlink_to(root / "a.txt")
    tid = await TaskStore(pool).create(
        created_by="admin",
        title="t",
        model="fake",
        prompt="p",
        max_attempts=3,
        idempotency_key=None,
    )
    task_id = tid[0].id
    report = await save_changes(
        files, artifacts, workspace_id=ws, conversation_id=None, task_id=task_id
    )
    assert [s.path for s in report.saved] == ["a.txt", "b.txt"]  # no symlink
    assert [s.model_dump() for s in report.skipped] == [{"path": "big.bin", "reason": "too_large"}]

    (root / "b.txt").unlink()
    monkeypatch.setattr(studio_files, "MAX_SNAPSHOT_FILES", 1)
    report = await save_changes(
        files, artifacts, workspace_id=ws, conversation_id=None, task_id=task_id
    )
    assert report.truncated and report.saved == []  # b.txt may only be past the cut
    monkeypatch.undo()
    report = await save_changes(
        files, artifacts, workspace_id=ws, conversation_id=None, task_id=task_id
    )
    assert [(s.path, s.deleted) for s in report.saved] == [("b.txt", True)]


async def test_a_failed_save_is_recorded_and_the_task_still_completes(
    tasks: TaskStore, pool: Pool, wsettings: Settings, tmp_path: Path
) -> None:
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("a file where the artifact root should be")
    task, _ = await tasks.create(
        created_by="admin",
        title="t",
        model="fake",
        prompt="p",
        max_attempts=3,
        idempotency_key=None,
    )
    await run(
        tasks,
        wsettings,
        ArtifactStore(pool, blocked),
        [calls(("write_file", {"path": "a.txt", "content": "x"})), reply("done")],
    )
    done = await tasks.get(task.id)
    assert done is not None and done.state == "completed"
    [failed] = await events(tasks, task.id, "artifacts_failed")
    assert failed["stage"] == "save" and "not-a-dir" in str(failed["error"])
    assert await versions(pool, task.id) == []


async def test_the_sandbox_saves_and_restores_bytes_as_the_task_user(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    settings = Settings(sandbox_root=str(root), sandbox_isolate_users=False)
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_sandbox_app(settings)), base_url="http://sb"
    )
    ws = uuid.uuid4()
    files = SandboxFiles(SandboxClient(http), ws)
    data = bytes(range(256)) * 3  # not UTF-8
    await files.write("img/logo.bin", data)
    assert (root / str(ws) / "img" / "logo.bin").read_bytes() == data
    snap = await files.snapshot()
    assert [(f.path, f.size, f.sha256) for f in snap.files] == [
        ("img/logo.bin", len(data), sha(data))
    ]
    assert await files.read("img/logo.bin") == data
    bad = await http.post(
        f"/v1/workspaces/{ws}/files",
        json={"op": "write_bytes", "path": "../x", "data": base64.b64encode(b"x").decode()},
    )
    assert bad.json() == {"ok": False, "result": None, "error": "Path escapes the workspace."}
    bad = await http.post(
        f"/v1/workspaces/{ws}/files", json={"op": "write_bytes", "path": "x", "data": "!!"}
    )
    assert bad.json()["error"] == "Data is not base64."
    await http.aclose()
