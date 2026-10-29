# ADR-0010 — Sandbox: one locked-down container, a user per task

**Status:** Accepted (2026-10-29; isolation model chosen by the owner)

**Context:** The requirements say model-generated shell never runs in the API
process and runs in isolated workers or sandboxes with filesystem, network, CPU,
memory and time bounds. Tasks run in the worker (ADR-0008), which until now had
file tools only. The VPS is shared with other services (dustline, filebrowser),
so a breakout must not reach the host.

**Options**
1. A separate long-lived sandbox container that the worker calls over HTTP.
2. A fresh container per command, started by the worker through the Docker
   socket.
3. A kernel-level sandbox (gVisor, Firecracker) installed on the host.

**Decision:** Option 1, picked by the owner. Option 2 gives the worker the Docker
socket, which is root on the VPS; option 3 needs host changes and is not needed
at this scale.

- **Service:** `seed_api.sandbox.server` (same image as the API, run with
  `--loop asyncio`, since uvloop cannot start processes as another user).
- **Network:** attached only to an internal Docker network (`internal: true`)
  shared with the worker: no route out, no DNS for outside names, no route to
  Postgres or the API. No `env_file`: it holds no secrets.
- **Privileges:** root inside the container only to switch users. `cap_drop:
  ALL` plus `SETUID`, `SETGID`, `CHOWN`, `KILL`; `no-new-privileges`; read-only
  root filesystem. Without `DAC_OVERRIDE` the server itself cannot enter or read
  any workspace.
- **Per-task user:** task *T* runs as uid `200000 + T mod 10⁹`. Its workspace
  `/workspaces/T` is created mode 0700 and owned by that uid; `/workspaces` is
  0711, so it cannot be listed. Commands and file operations (list, read,
  write) for *T* all run as that uid, so the kernel keeps tasks apart and a
  symlink planted in one workspace cannot be followed into another.
- **Limits per command:** wall time (`SEED_SANDBOX_COMMAND_TIMEOUT_SECONDS`,
  default 60), address space (512 MiB), CPU seconds (60), processes per task
  (64), file size (64 MiB), 256 open files, no core dumps; stdout and stderr are
  each cut at 8 KiB. When a command ends or times out, its process group and
  every process of the task's uid are killed: nothing runs between commands.
  Container caps: 768 MiB, 1 CPU, 256 processes, workspaces on a 256 MiB tmpfs.
- **Worker:** with `SEED_SANDBOX_URL` set, tasks get `run_command` plus file
  tools that go through the sandbox; the worker never touches workspace files.
  Without it, tasks get local file tools and no commands. In-request Chat runs
  keep local file tools and never get `run_command`.

**Consequences**
- Workspaces are ephemeral: they live on the sandbox's tmpfs and are lost when
  it restarts (artifact storage is M6). A task resumed after such a restart
  finds an empty workspace.
- No disk quota per task beyond the shared 256 MiB tmpfs; one task can fill it.
- `run_command` does not ask for human approval: it can only affect its own
  workspace. Approval policies arrive with tools that reach outside (network,
  connectors).
- Tasks share one kernel and one container; a kernel exploit would cross tasks.
  Acceptable for a single-tenant deployment; revisit before multi-tenant use.
- The image has Python and coreutils, not git or compilers.
