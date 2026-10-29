"""Runs one command with resource limits and makes sure nothing outlives it."""

import asyncio
import contextlib
import os
import resource
import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .protocol import MAX_OUTPUT_BYTES, ExecResult

# Task user ids live far above any id the image or host uses.
UID_BASE = 200_000
UID_SPAN = 1_000_000_000
PATH = "/usr/local/bin:/usr/bin:/bin"


@dataclass(frozen=True)
class Limits:
    memory_bytes: int
    cpu_seconds: int
    max_processes: int
    max_file_bytes: int
    max_open_files: int = 256


def task_uid(task_id: uuid.UUID) -> int:
    return UID_BASE + task_id.int % UID_SPAN


def _apply_limits(limits: Limits, own_user: bool) -> None:
    """Runs in the child after it has switched user, before exec."""
    os.umask(0o077)
    caps = [
        (resource.RLIMIT_AS, limits.memory_bytes),
        (resource.RLIMIT_CPU, limits.cpu_seconds),
        (resource.RLIMIT_FSIZE, limits.max_file_bytes),
        (resource.RLIMIT_NOFILE, limits.max_open_files),
        (resource.RLIMIT_CORE, 0),
    ]
    if own_user:  # the process count is per user, so it only means something per task
        caps.append((resource.RLIMIT_NPROC, limits.max_processes))
    for which, value in caps:
        resource.setrlimit(which, (value, value))


class _Output:
    """The first `cap` bytes of a stream, and whether there was more."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.kept = bytearray()
        self.truncated = False

    async def drain(self, stream: asyncio.StreamReader) -> None:
        while chunk := await stream.read(65536):
            room = self.cap - len(self.kept)
            self.kept += chunk[:room]
            self.truncated = self.truncated or len(chunk) > room

    def text(self) -> str:
        return self.kept.decode("utf-8", "replace")


def _kill_user(uid: int) -> None:
    """Kills every process running as `uid`: a command's background children
    and anything that left its process group."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        with contextlib.suppress(OSError):
            status = (entry / "status").read_text()
            line = next(x for x in status.splitlines() if x.startswith("Uid:"))
            if int(line.split()[1]) == uid:
                os.kill(int(entry.name), signal.SIGKILL)


def _cleanup(pgid: int, uid: int | None) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)
    if uid is not None:
        _kill_user(uid)


async def run(
    argv: list[str],
    *,
    cwd: Path,
    uid: int | None,
    stdin: bytes,
    timeout_s: float,
    limits: Limits,
    max_output: int = MAX_OUTPUT_BYTES,
) -> ExecResult:
    """Runs `argv` in `cwd` as `uid` (None: as this process's user, for tests).
    When it ends or times out, its whole process group and, with a uid, every
    process of that user is killed, so nothing keeps running between commands."""
    env = {"PATH": PATH, "HOME": str(cwd), "TMPDIR": str(cwd), "LANG": "C.UTF-8"}
    started = time.monotonic()
    # Enter the workspace only after switching user: the sandbox's root has no
    # capability to bypass permissions, so it cannot enter a task's 0700 directory.
    proc = await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-c",
        'cd -- "$0" && exec "$@"',
        str(cwd),
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd="/",
        env=env,
        start_new_session=True,
        user=uid,
        group=uid,
        extra_groups=[] if uid is not None else None,
        preexec_fn=lambda: _apply_limits(limits, uid is not None),
    )
    assert proc.stdin and proc.stdout and proc.stderr  # noqa: S101 - PIPE guarantees them
    out, err = _Output(max_output), _Output(MAX_OUTPUT_BYTES)
    readers = asyncio.gather(out.drain(proc.stdout), err.drain(proc.stderr))
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        proc.stdin.write(stdin)
        await proc.stdin.drain()
    proc.stdin.close()
    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout_s)
    except TimeoutError:
        timed_out = True
    _cleanup(proc.pid, uid)
    code = await proc.wait()
    try:
        # Only a process that escaped both the group and the uid sweep (possible
        # only without a uid, in tests) could still hold the pipes open.
        await asyncio.wait_for(readers, 2)
    except TimeoutError:
        out.truncated = err.truncated = True
    return ExecResult(
        exit_code=None if timed_out or code < 0 else code,
        signal=-code if code < 0 else None,
        stdout=out.text(),
        stderr=err.text(),
        stdout_truncated=out.truncated,
        stderr_truncated=err.truncated,
        timed_out=timed_out,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
