# ADR-0001 — Modular monolith with dedicated workers

**Status:** Accepted (2026-10-28)
**Context:** Directive v1.1 names seven subsystems and demands low idle footprint on modest hosts.
**Options:** microservice per subsystem; single process doing everything; modular monolith + workers.
**Decision:** One FastAPI deployable with subsystem packages; separate worker processes for long-running agent execution (M3); separate sandbox for tool execution.
**Consequences:** One deploy, one schema, cheap idle. Package boundaries must be kept by review (no cross-package internals). Workers can scale independently.
