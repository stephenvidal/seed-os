"""The sandbox: command limits, cleanup, file operations, and per-task users."""

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from seed_api.config import Settings
from seed_api.core.messages import ToolCall
from seed_api.core.tools import ToolRegistry
from seed_api.sandbox import runner
from seed_api.sandbox.client import SandboxClient, sandbox_tools
from seed_api.sandbox.protocol import MAX_OUTPUT_BYTES
from seed_api.sandbox.server import create_sandbox_app

pytestmark = pytest.mark.anyio
LIMITS = runner.Limits(
    memory_bytes=256 * 1024 * 1024, cpu_seconds=5, max_processes=32, max_file_bytes=1024 * 1024
)


def alive(pid: int) -> bool:
    """Running, as opposed to gone or a zombie waiting for its reaper."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def sandbox_settings(root: Path, isolate: bool) -> Settings:
    return Settings(
        sandbox_root=str(root),
        sandbox_isolate_users=isolate,
        sandbox_command_timeout_seconds=5,
        sandbox_memory_mb=256,
        sandbox_cpu_seconds=2,
    )


async def sh(cmd: str, tmp: Path, *, timeout: float = 5, uid: int | None = None, **kw: object):  # type: ignore[no-untyped-def]
    return await runner.run(
        ["/bin/sh", "-c", cmd], cwd=tmp, uid=uid, stdin=b"", timeout_s=timeout, limits=LIMITS, **kw
    )


async def test_command_output_and_exit_code(tmp_path: Path) -> None:
    r = await sh("echo out; echo err >&2; pwd; exit 3", tmp_path)
    assert r.exit_code == 3 and r.signal is None and not r.timed_out
    assert r.stdout == f"out\n{tmp_path}\n" and r.stderr == "err\n"


async def test_environment_is_minimal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_OLLAMA_API_KEY", "must-not-leak")
    r = await sh("env | sort", tmp_path)
    assert "must-not-leak" not in r.stdout
    names = sorted(line.split("=")[0] for line in r.stdout.splitlines())
    assert names == ["HOME", "LANG", "OLDPWD", "PATH", "PWD", "TMPDIR"]  # sh adds the PWDs


async def test_stdin_is_passed(tmp_path: Path) -> None:
    r = await runner.run(
        ["/bin/sh", "-c", "tr a-z A-Z"],
        cwd=tmp_path,
        uid=None,
        stdin=b"hello",
        timeout_s=5,
        limits=LIMITS,
    )
    assert r.stdout == "HELLO"


async def test_timeout_kills_the_command_and_its_children(tmp_path: Path) -> None:
    r = await sh("sleep 30 & echo $! > child.pid; sleep 30", tmp_path, timeout=0.5)
    assert r.timed_out and r.exit_code is None and r.signal == 9
    assert r.duration_ms < 5000
    pid = int((tmp_path / "child.pid").read_text())
    await asyncio.sleep(0.1)
    assert not alive(pid)


async def test_background_process_does_not_outlive_its_command(tmp_path: Path) -> None:
    r = await sh("sleep 30 & echo $! > child.pid; echo started", tmp_path)
    assert r.exit_code == 0 and r.stdout == "started\n" and r.duration_ms < 2500
    pid = int((tmp_path / "child.pid").read_text())
    await asyncio.sleep(0.1)
    assert not alive(pid)


async def test_output_is_capped(tmp_path: Path) -> None:
    r = await sh(f"head -c {MAX_OUTPUT_BYTES * 4} /dev/zero | tr '\\0' x", tmp_path)
    assert r.stdout_truncated and len(r.stdout) == MAX_OUTPUT_BYTES and r.exit_code == 0


async def test_memory_limit(tmp_path: Path) -> None:
    r = await sh(f"{sys.executable} -c 'b = bytearray(512 * 1024 * 1024)'", tmp_path)
    assert r.exit_code != 0 and "MemoryError" in r.stderr


async def test_file_size_limit(tmp_path: Path) -> None:
    r = await sh("head -c 2000000 /dev/zero > big", tmp_path)
    assert r.exit_code != 0
    assert (tmp_path / "big").stat().st_size <= LIMITS.max_file_bytes


async def test_cpu_limit(tmp_path: Path) -> None:
    limits = runner.Limits(
        memory_bytes=LIMITS.memory_bytes,
        cpu_seconds=1,
        max_processes=32,
        max_file_bytes=LIMITS.max_file_bytes,
    )
    r = await runner.run(
        [sys.executable, "-c", "while True: pass"],
        cwd=tmp_path,
        uid=None,
        stdin=b"",
        timeout_s=10,
        limits=limits,
    )
    assert not r.timed_out and r.exit_code is None and r.signal in (9, 24)


@pytest.fixture
async def tools(tmp_path: Path) -> AsyncIterator[tuple[ToolRegistry, uuid.UUID]]:
    app = create_sandbox_app(sandbox_settings(tmp_path, isolate=False))
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sandbox")
    task_id = uuid.uuid4()
    yield ToolRegistry(sandbox_tools(SandboxClient(http), task_id, 5)), task_id
    await http.aclose()


async def call(reg: ToolRegistry, name: str, **args: object):  # type: ignore[no-untyped-def]
    return await reg.execute(ToolCall(id="c", name=name, arguments=dict(args)))


async def test_tools_write_run_read_list(
    tools: tuple[ToolRegistry, uuid.UUID], tmp_path: Path
) -> None:
    reg, task_id = tools
    assert [s.name for s in reg.specs()] == ["list_files", "read_file", "write_file", "run_command"]
    w = await call(reg, "write_file", path="src/a.py", content="print(6 * 7)\n")
    assert w.ok and w.output == {"path": "src/a.py", "bytes_written": 13}
    run = await call(reg, "run_command", command="python3 src/a.py > out.txt && cat out.txt")
    assert run.ok and run.output and run.output["stdout"] == "42\n" and run.output["exit_code"] == 0
    read = await call(reg, "read_file", path="out.txt")
    assert read.ok and read.output == {"path": "out.txt", "content": "42\n"}
    listed = await call(reg, "list_files")
    assert listed.ok and listed.output
    assert [e["path"] for e in listed.output["entries"]] == ["out.txt", "src", "src/a.py"]
    assert (tmp_path / str(task_id) / "out.txt").read_text() == "42\n"


async def test_tool_errors_are_typed(tools: tuple[ToolRegistry, uuid.UUID]) -> None:
    reg, _ = tools
    escape = await call(reg, "read_file", path="../other/secret")
    assert not escape.ok and escape.error_kind == "tool_error" and "escapes" in (escape.error or "")
    missing = await call(reg, "read_file", path="nope.txt")
    assert not missing.ok and "No such file" in (missing.error or "")
    bad = await call(reg, "run_command", command="")
    assert bad.error_kind == "invalid_arguments"
    slow = await call(reg, "run_command", command="sleep 30", timeout_s=600)
    assert slow.ok and slow.output and slow.output["timed_out"]  # capped at the 5 s maximum
    assert slow.output["exit_code"] is None and slow.duration_ms < 10_000


async def test_unreachable_sandbox_is_a_tool_error() -> None:
    http = httpx.AsyncClient(base_url="http://127.0.0.1:9")  # nothing listens on port 9
    reg = ToolRegistry(sandbox_tools(SandboxClient(http), uuid.uuid4(), 5))
    out = await call(reg, "run_command", command="true")
    assert not out.ok and "unreachable" in (out.error or "")
    await http.aclose()


def test_server_rejects_bad_task_ids_and_requests(tmp_path: Path) -> None:
    with TestClient(create_sandbox_app(sandbox_settings(tmp_path, isolate=False))) as c:
        assert c.get("/healthz").json() == {"status": "ok"}
        assert c.post("/v1/workspaces/..%2F..%2Fetc/exec", json={"command": "id"}).status_code in (
            404,
            422,
        )
        r = c.post(f"/v1/workspaces/{uuid.uuid4()}/exec", json={"command": "x" * 20_000})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert list(tmp_path.iterdir()) == []  # nothing was created for rejected requests


def test_server_caps_the_timeout(tmp_path: Path) -> None:
    settings = sandbox_settings(tmp_path, isolate=False).model_copy(
        update={"sandbox_command_timeout_seconds": 0.5}
    )
    with TestClient(create_sandbox_app(settings)) as c:
        body = {"command": "sleep 30", "timeout_s": 600}
        r = c.post(f"/v1/workspaces/{uuid.uuid4()}/exec", json=body).json()
    assert r["timed_out"] and r["duration_ms"] < 5000


@pytest.mark.skipif(os.geteuid() == 0, reason="checks the non-root refusal")
def test_server_refuses_to_start_without_root_when_isolating(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="needs root"):
        with TestClient(create_sandbox_app(sandbox_settings(tmp_path, isolate=True))):
            pass


# Per-task users need root, as in the sandbox container. CI runs these with sudo
# and sets SEED_REQUIRE_ROOT_TESTS so they cannot be skipped there.
def _need_root() -> None:
    if os.geteuid() != 0:
        if os.environ.get("SEED_REQUIRE_ROOT_TESTS"):
            pytest.fail("root is required (SEED_REQUIRE_ROOT_TESTS is set)")
        pytest.skip("per-task users need root")


@pytest.fixture
def isolated(tmp_path: Path) -> Path:
    _need_root()
    # As the sandbox's workspace root: task users may pass through, not list.
    for d in (tmp_path, *tmp_path.parents[:2]):
        os.chmod(d, 0o711)  # noqa: S103
    return tmp_path


def test_each_task_has_its_own_user(isolated: Path) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    with TestClient(create_sandbox_app(sandbox_settings(isolated, isolate=True))) as c:

        def run(task: uuid.UUID, cmd: str) -> dict:  # type: ignore[type-arg]
            r = c.post(f"/v1/workspaces/{task}/exec", json={"command": cmd})
            assert r.status_code == 200, r.text
            return r.json()  # type: ignore[no-any-return]

        def write(task: uuid.UUID, path: str) -> dict:  # type: ignore[type-arg]
            body = {"op": "write", "path": path, "content": "secret"}
            return c.post(f"/v1/workspaces/{task}/files", json=body).json()  # type: ignore[no-any-return]

        assert write(a, "secret.txt")["ok"]
        assert run(a, "id -u")["stdout"] == f"{runner.task_uid(a)}\n"
        assert (isolated / str(a)).stat().st_uid == runner.task_uid(a)
        assert (isolated / str(a) / "secret.txt").stat().st_uid == runner.task_uid(a)

        # Task b can neither read a's files nor plant a symlink that the file tools follow.
        peek = run(b, f"cat ../{a}/secret.txt")
        assert peek["exit_code"] != 0 and "Permission denied" in peek["stderr"]
        assert run(b, f"ln -s ../{a}/secret.txt link && echo ok")["stdout"] == "ok\n"
        follow = c.post(f"/v1/workspaces/{b}/files", json={"op": "read", "path": "link"}).json()
        assert not follow["ok"]
        assert run(b, "ls ..")["exit_code"] != 0  # the root cannot be listed

        # Nothing survives a command, even a process that left its process group.
        escape = run(a, "setsid sleep 30 > /dev/null 2>&1 & echo $!; sleep 0.5")
        assert not alive(int(escape["stdout"]))


def test_process_limit_is_per_task(isolated: Path) -> None:
    settings = sandbox_settings(isolated, isolate=True).model_copy(
        update={"sandbox_max_processes": 8}
    )
    with TestClient(create_sandbox_app(settings)) as c:
        r = c.post(
            f"/v1/workspaces/{uuid.uuid4()}/exec",
            json={"command": "for i in $(seq 20); do sleep 2 & done; wait; echo done"},
        ).json()
    assert "fork" in r["stderr"].lower() or "resource" in r["stderr"].lower()
