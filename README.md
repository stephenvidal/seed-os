# SEED OS

Greenfield, production-oriented build of **SEED OS**, executed in **Claude Code**
under **Directive v1.0**.

| | |
|---|---|
| Project | SEED OS |
| Repository | `stephenvidal/seed-os` (private) |
| Execution environment | Claude Code |
| Development approach | Greenfield, production-oriented, iterative delivery |
| Directive | v1.0 — see [DIRECTIVE.md](DIRECTIVE.md) |
| Status | Repository scaffolded. Product definition not yet ratified (enters at Directive v1.1). |

## What is in here

| Path | Purpose |
|---|---|
| `DIRECTIVE.md` | The governing directive. Versioned, amendment-controlled. Read before any work. |
| `CLAUDE.md` | Execution rules for Claude Code in this repository. |
| `docs/decisions.md` | Decision log (ADR-style, append-only). |
| `docs/progress.md` | Iteration log: what shipped, what was verified, what is open. |

## Ground rules

1. **The directive is the contract.** Work that is not traceable to a directive clause is out of scope.
2. **Iterative delivery, production bar.** Every iteration ends with something runnable, tested, and documented — not a scaffold that "will be wired up later."
3. **Verify by observation.** Tests, commands, or rendered output. A self-report is not evidence.
4. **Decisions are recorded.** Any choice that constrains future work lands in `docs/decisions.md` with its reason.
5. **No silent scope.** Product scope is defined in the directive, never invented in a branch.

## Next step

Author the SEED OS product definition and ratify it as **Directive v1.1** (see
`DIRECTIVE.md` §6). Until then the repository holds method, not product.
