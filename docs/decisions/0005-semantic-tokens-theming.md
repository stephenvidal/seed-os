# ADR-0005 — Semantic OKLCH tokens with data-theme switching

**Status:** Accepted (2026-10-28)
**Context:** Light, dark, system preference, persistence, accessible contrast, no flash.
**Decision:** All colors are semantic CSS variables in OKLCH under `[data-theme]`, exposed to Tailwind via `@theme inline`. Inline pre-paint script sets the theme; `ThemeProvider` owns it after mount.
**Consequences:** Components cannot drift to raw colors; adding a theme is one token block. The inline script needs CSP `'unsafe-inline'` until replaced with a hash.
