# Progress — SEED OS

Append-only, one block per session. Format: changed / tested / not tested / open.

---

## 2026-10-28 — Iteration 0: repository frame

**Intent:** Establish the repository, the governing directive (v1.0), and the
execution rules for Claude Code.

**Changed**
- `README.md` — project frame, repository map, ground rules.
- `DIRECTIVE.md` — Directive v1.0: scope, execution environment, approach,
  definition of done, gate, non-negotiables, change control.
- `CLAUDE.md` — Claude Code session protocol, hard rules, production bar,
  verification checklist.
- `docs/decisions.md` — D-001 and the open-questions register.
- `.gitignore` — editor/OS noise, environment files, dependency and build
  directories, language-agnostic so no toolchain is prejudged.

**Tested**
- `git status --short` clean after commit; `git ls-remote origin` reports the
  pushed commit SHA (see commit on `main`).
- Repository visibility read back from the GitHub API: private, owner
  `stephenvidal`.

**Not tested**
- Nothing is executable yet, so no runtime verification exists for this iteration
  beyond repository state. That is the correct state for Iteration 0.

**Open**
- Directive v1.1 (product definition) is the blocker for Iteration 1.
