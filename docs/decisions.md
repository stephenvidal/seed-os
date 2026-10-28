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
