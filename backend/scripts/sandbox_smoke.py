"""Checks a running sandbox container from the inside (stdlib only).

    docker compose exec -T sandbox python - < backend/scripts/sandbox_smoke.py

Exits non-zero, naming the failed check, if any isolation property is missing.
CI runs it against the compose service; see docs/progress.md for a local run.
"""

import json
import sys
import urllib.request
import uuid

BASE = "http://127.0.0.1:8100/v1/workspaces"
failures: list[str] = []


def post(task: uuid.UUID, path: str, body: dict) -> dict:  # type: ignore[type-arg]
    req = urllib.request.Request(  # noqa: S310 - fixed local URL
        f"{BASE}/{task}/{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - fixed local URL
        return json.loads(r.read())  # type: ignore[no-any-return]


def run(task: uuid.UUID, command: str) -> dict:  # type: ignore[type-arg]
    return post(task, "exec", {"command": command, "timeout_s": 20})


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{'' if ok else f': {detail}'}")
    if not ok:
        failures.append(name)


a, b = uuid.uuid4(), uuid.uuid4()
uid = run(a, "id -u")["stdout"].strip()
check("commands run as an unprivileged per-task user", uid not in ("0", "10001"), uid)
caps = run(a, "grep CapEff /proc/self/status")["stdout"].split()
check("commands have no capabilities", caps[-1:] == ["0000000000000000"], caps)
net = run(a, "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 443), 3)\"")
check("no network route out", net["exit_code"] != 0, net)
dns = run(a, "python3 -c \"import socket; socket.getaddrinfo('example.com', 443)\"")
check("no DNS resolution of outside names", dns["exit_code"] != 0, dns)
check("file write", post(a, "files", {"op": "write", "path": "s.txt", "content": "x"})["ok"])
peek = run(b, f"cat ../{a}/s.txt")
check("another task cannot read the file", peek["exit_code"] != 0, peek)
check("workspace root cannot be listed", run(b, "ls ..")["exit_code"] != 0)
env = run(b, "cat /proc/1/environ")
check("server's environment is unreadable", env["exit_code"] != 0, env)
ro = run(b, "touch /usr/x")
check("root filesystem is read-only", ro["exit_code"] != 0, ro)
fork = run(b, "for i in $(seq 200); do sleep 2 & done 2>&1; wait")
check("process count is capped", "fork" in (fork["stdout"] + fork["stderr"]).lower(), fork)
left = run(b, "sleep 30 & echo started")
check("background processes end with the command", left["duration_ms"] < 5000, left)
sys.exit(1 if failures else 0)
