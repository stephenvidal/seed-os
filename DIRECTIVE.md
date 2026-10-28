# Directive — SEED OS

**Directive Version 1.0** · Ratified 2026-10-28 · Status: ACTIVE

| Field | Value |
|---|---|
| Project | SEED OS |
| Repository | `stephenvidal/seed-os` |
| Execution Environment | Claude Code |
| Development Approach | Greenfield, production-oriented, iterative delivery |
| Directive Version | 1.0 |

Directive v1.0 establishes the project's **frame**: repository, execution
environment, delivery method, and change control. It deliberately does **not**
define the product. Product scope is a directive amendment (§6), so that no
implementation decision can precede the scope that justifies it.

---

## 1. Scope of this directive

**In scope (v1.0):**

- Repository `stephenvidal/seed-os`, private, `main` as the trunk.
- Claude Code as the execution environment, operating under `CLAUDE.md`.
- The iterative delivery method in §3 and the gate in §4.
- Decision log and iteration log as first-class artifacts.

**Out of scope (deferred to a later amendment):**

- What SEED OS is: its purpose, users, capabilities, interfaces, non-goals.
- Technology selection (language, runtime, storage, transport).
- Deployment target and operational envelope.

Any work that assumes answers to the out-of-scope items is premature and must be
recorded as an open question in `docs/decisions.md` instead of implemented.

## 2. Execution environment — Claude Code

1. Claude Code is the implementer. It reads `CLAUDE.md` and this directive at the
   start of every session; neither may be edited by the implementation itself.
2. Claude Code works in small, reviewable increments. A change that cannot be
   reviewed in one pass is split.
3. Claude Code does not merge its own work into `main` without the gate in §4.
4. Deterministic work (branching, commits, tests, CI) is automated; judgement
   (scope, architecture, product) stays with the owner.
5. Every session ends by appending to `docs/progress.md`: what changed, what was
   verified, what was not.

## 3. Development approach — greenfield, production-oriented, iterative

- **Greenfield.** No inherited codebase, no compatibility debt. Every file exists
  because a clause of the directive requires it.
- **Production-oriented.** From the first iteration the standard is production:
  typed boundaries, explicit error paths, tests that can fail, no TODO-driven
  architecture, no placeholder that ships. "Prototype later becomes real" is not
  an accepted path — prototypes live in `spikes/` and are deleted or promoted.
- **Iterative delivery.** Work proceeds in numbered iterations. Each iteration
  has a single sentence of intent, a definition of done, and a demonstration.
  Iterations do not overlap in scope.

### Definition of done (per iteration)

An iteration is done only when all four hold:

1. **Runs.** The deliverable executes from a clean checkout with documented
   commands.
2. **Tested.** Automated tests cover the behaviour the iteration claims, and the
   observed test output is cited in `docs/progress.md`.
3. **Documented.** README / docs describe the shipped behaviour as it is, not as
   intended.
4. **Bounded.** The diff touches only what the iteration needed; every changed
   file is justified in one line.

## 4. Gate

An iteration moves to the next only after an **exit review** of the artifact —
not of the report describing it. The review answers:

- Does the artifact satisfy the iteration's definition of done, verified by
  running it?
- Are the tests real (can they fail)?
- Did scope creep into the diff?

A failed gate produces a remediation brief and returns to the same iteration.
Iteration numbers do not advance past an open gate.

## 5. Non-negotiables

1. Never claim a result that was not observed. Cite the command, test line, or
   artifact path.
2. Never invent product requirements. Unknowns are logged as open questions.
3. Never leave the trunk broken. `main` is always runnable.
4. Never bake secrets into the repository; configuration arrives by environment.
5. Never let a decision exist only in a chat. It belongs in `docs/decisions.md`.

## 6. Change control

- The directive is versioned `MAJOR.MINOR`. Ratified versions are immutable once
  merged; they are amended, never rewritten.
- **MINOR** — adds or clarifies scope without invalidating prior work.
- **MAJOR** — changes the frame (execution environment, approach, or a reversal
  that invalidates shipped work).
- Every amendment states: what changed, why, and what prior work it affects.
  It is recorded as a new section at the end of this file with its own version
  heading, and logged in `docs/decisions.md`.
- The next scheduled amendment is **v1.1: SEED OS product definition**.

---

## Amendment log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-28 | Initial frame: repository, Claude Code execution environment, greenfield iterative method, gate, change control. Product scope deferred. |
| 1.1 | 2026-10-28 | Product definition: SEED OS master directive ratified (see below and `docs/product-vision.md`). |

---

## Directive v1.1 — SEED OS product definition

**Ratified 2026-10-28** by the owner (Stephen) in the project thread. MINOR
amendment: adds scope, invalidates no prior work. v1.0 text above is unchanged.

**What changed.** The product is now defined. SEED OS is a self-hostable,
model-agnostic autonomous agent platform ("From intention to execution"):
native chat, durable task orchestration (SEED Flow), an independent agent
runtime (SEED Core), artifacts (SEED Studio), memory, integrations, and
administration, delivered through a premium web workspace.

**Authoritative source.** The owner's master directive is distilled, section by section, into
`docs/product-vision.md` (mission, identity, experience, design bar),
`docs/requirements.md` (functional areas, runtime, flow, tools, memory, security,
standards), and `docs/roadmap.md` (Milestones 0–9 and the mandatory end-to-end
acceptance test). Where those documents and v1.0 §3–§5 appear to disagree, v1.0
process rules (definition of done, gate, non-negotiables) still govern *how*
work is done; v1.1 governs *what* is built.

**Technology envelope.** Recommended architecture ratified as a starting point,
to be validated per ADR: React + TypeScript + Vite + Tailwind; Python + FastAPI
+ Pydantic; PostgreSQL; dedicated workers; SSE; filesystem artifact storage;
Docker Compose. See `docs/decisions/`.

**Hard boundaries carried from the master directive.** Never modify
`stephenvidal/agent-native-os` or the running Hermes Agent installation. SEED
does not depend on Claude Code or Hermes at runtime. Hosted GitHub Actions
minutes are unavailable; verification is local.

**Prior work affected.** `CLAUDE.md` environment note updated (toolchain now
ratified). `docs/decisions.md` open questions 1–3 are closed by D-002.
