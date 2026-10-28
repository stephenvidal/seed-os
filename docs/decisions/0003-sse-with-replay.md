# ADR-0003 — Server-Sent Events with persisted sequence ids

**Status:** Accepted, implementation M3/M4 (2026-10-28)
**Context:** Clients need live task/chat progress, reconnection, and missed-event replay; tasks must outlive connections.
**Decision:** Events are written to Postgres with a per-stream monotonic sequence before being emitted over SSE; clients resume with `Last-Event-ID`. Commands are plain POSTs.
**Consequences:** No WebSocket server state; replay is a query. Proxies must not buffer `/api/.../events` (nginx `proxy_buffering off` when added).
