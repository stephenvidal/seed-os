# ADR-0002 — Vite + React SPA (not Next.js)

**Status:** Accepted (2026-10-28)
**Context:** Directive allows Vite or Next.js "according to actual requirements". SEED is fully authenticated, has no public/SEO pages, and already has a Python backend.
**Decision:** Vite + React + TypeScript SPA served by nginx; Tailwind v4 on semantic CSS tokens; TanStack Query; Radix primitives; cmdk; Lucide.
**Consequences:** No Node runtime in production (5 MiB nginx). No SSR — first paint after JS (mitigated by pre-paint theme script and small bundle). Code-splitting per route to be added when pages gain weight.
