# ADR-0014 — Artifacts: every changed file is saved after every run

**Status:** Accepted (2026-10-29)

**Context:** M6 needs artifacts with versions and previews, and the acceptance test
needs files that survive a restart and can be modified later. A task's files live
in its workspace on the sandbox's tmpfs (ADR-0010), one workspace per conversation
(ADR-0011), and vanish when the sandbox restarts. The owner chose (D-015) that
every file a run creates or changes becomes an artifact, rather than only files the
agent publishes.

**Options**
1. Keep workspaces on a persistent volume and treat them as the artifacts.
2. A `publish` tool; only published files are saved.
3. After every run, save each new, changed or deleted file as a version, in a
   store the sandbox cannot touch.

**Decision:** Option 3.

- **When:** after every run, however it ended (completed, failed, canceled, paused
  for approval, handed back at shutdown), while the worker still holds the lease.
  Not after a run whose lease was lost: another worker owns the task.
- **What:** the worker takes a snapshot of the workspace (every regular file, path
  order, SHA-256; no symlinks), compares it with the latest saved version of each
  path and saves only differences. A path missing from a complete snapshot gets a
  "deleted" version. Limits: files over 1 MiB are skipped and named in the event;
  a snapshot stops at 500 files, and then no deletions are recorded.
- **Where:** content is stored once per SHA-256 under `SEED_ARTIFACT_ROOT`
  (`blobs/ab/abcd…`), written to a temporary name and renamed. Postgres holds
  `artifacts` (one row per workspace path, linked to its conversation, deleted with
  it) and `artifact_versions` (version number, the task that made it, hash, size).
  Only the worker writes; the sandbox has no access to the store.
- **Restore:** before a run, if the workspace has no files and saved artifacts
  exist, the worker writes back the latest version of every file that is not
  deleted. A workspace with any file in it is left alone.
- **Sandbox protocol:** three file ops, run as the task's own user like the
  others: `snapshot`, `read_bytes`, `write_bytes` (base64).
- **Events:** `artifacts_saved {saved[{path, version, deleted}], skipped[{path,
  reason}], truncated}` when anything was saved or skipped; `workspace_restored
  {files}`; `artifacts_failed {stage, error}`. A failed save or restore never
  changes how the task ends.

**Consequences**
- Versions follow messages: a file's history shows which answer changed it.
  Edited or regenerated versions of a message (ADR-0013) share the workspace, so
  they add versions to the same files.
- Content of deleted conversations stays on disk until a cleanup exists (blobs are
  shared by hash, so they cannot simply be removed with the rows).
- Saving reads every file each run to hash it: fine for small workspaces, costly
  for hundreds of large files. Revisit with change tracking if it shows up.
- A restore brings back files, not other state (installed packages, processes).
- Backups must take Postgres and the artifact volume together.
- Studio (browse, versions, download, isolated HTML preview) reads this store.
