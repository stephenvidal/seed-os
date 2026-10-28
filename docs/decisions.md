# Decisions — SEED OS

Append-only. Newest at the bottom. Each entry: context, options considered,
choice, reason, consequences.

---

## D-001 — Repository initialized under Directive v1.0 with product scope deferred

**Date:** 2026-10-28

**Context:** Directive v1.0 fixes the execution environment (Claude Code), the
approach (greenfield, production-oriented, iterative delivery), and the
repository, but carries no product definition. Implementation had to either wait
for the product spec or start on the frame alone.

**Options:**
1. Wait for a full product spec before creating anything.
2. Create the repository and governing documents now, deferring product scope to
   Directive v1.1.
3. Infer a plausible product from the name "SEED OS" and build a scaffold.

**Choice:** Option 2.

**Reason:** The frame is fully specified by the directive as given; the product is
not. Building the repository and method now makes the next step concrete, while
option 3 would have manufactured requirements the owner never ratified.

**Consequences:** The repository contains method, not product. The first real
implementation iteration cannot start until Directive v1.1 defines scope,
non-goals, and the first milestone.

---

## Open questions

1. **What is SEED OS?** Purpose, target user, core capability set, and non-goals.
   Blocking Directive v1.1.
2. **Technology envelope** — language/runtime/storage. Not ratifiable before (1).
3. **Operational target** — local-first, self-hosted, or hosted. Not ratifiable
   before (1).

---

## D-002 — Directive v1.1 ratified; recommended stack adopted

**Date:** 2026-10-28

**Context:** The owner supplied the full SEED OS master directive in the project
thread, defining the product, its milestones, and a recommended architecture.
Open questions 1–3 above are answered by it.

**Options:** (1) adopt the recommended stack as-is; (2) re-evaluate every layer
before writing code; (3) adopt it, validating each layer with an ADR as it is
built.

**Choice:** Option 3.

**Reason:** The directive says "validate choices before implementation" and also
"do not substitute lengthy planning for implementation". ADRs 0001–0005 record
the validated choices for what Iteration 1 builds; later layers get ADRs when
they are built.

**Consequences:** Open questions 1–3 are closed. The product scope lives in
`docs/product-vision.md`, `docs/requirements.md`, `docs/roadmap.md`. CLAUDE.md's
"no toolchain ratified" note is superseded. Host reality differs from CLAUDE.md
(Node 22 / Python 3.13, not Node 20 / 3.14); code targets Python ≥ 3.12, Node ≥ 20.

## Open questions (as of Iteration 1)

4. **CSRF strategy** before any internet-facing deployment — double-submit token
   vs. Origin check. Due with M3 auth.
5. **Default model routing** (which provider/model per task class) — needs owner
   input on budget; due M2.
6. **Self-hosted CI runner** — hosted Actions minutes are blocked; verification is
   local until the owner decides.
