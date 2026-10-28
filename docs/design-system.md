# Design system — SEED

Source of truth: `frontend/src/styles/index.css` (tokens) and
`frontend/src/components/ui` (primitives). This document describes them as built.

## Principles
Calm, dense-but-breathable, precise. One accent, used sparingly for focus,
primary action, and live state. Hierarchy from type weight and surface steps,
not from color or shadow. No gradients, glows, or glass; blur only on the sticky
top bar for legibility.

## Color
Semantic tokens only; components never use raw colors. OKLCH, cool graphite
neutrals with a faint green bias (hue 165), single jade accent (hue 163).

| Token | Role |
|---|---|
| `bg` | App canvas |
| `surface-1/2/3` | Panels → hover/inset → selected |
| `border`, `border-strong` | Hairlines, hover hairlines |
| `fg`, `fg-muted`, `fg-subtle` | Text tiers |
| `accent`, `accent-hover`, `accent-fg` | Primary action, focus, active nav |
| `accent-soft`, `accent-soft-fg` | Live/positive badges, selection |
| `danger*`, `warning*` | Errors, caution |
| `ring`, `scrim`, `shadow-pop` | Focus ring, overlays, popovers |

Light and dark are full token sets under `[data-theme]`. The theme is applied
before first paint by an inline script in `index.html` (no flash) and then owned
by `ThemeProvider` (light / dark / system, persisted to `localStorage`
`seed.theme`, follows OS changes live).

## Type
Inter Variable (UI) with `cv11`/`ss01`, JetBrains Mono Variable for numbers, ids,
and telemetry (tabular). Scale: 11 / 12 / 13 (body) / 14 / 22 (page title,
-0.015em). Section labels: 11px uppercase, 0.08em tracking.

## Shape and space
Radii: 6px controls, 10px panels, full for pills/avatars — nothing else. 4px
spacing grid; panel headers 40px, top bar 48px, nav rows 32px. Content max-width
1200px.

## Motion
150ms color transitions, 200–250ms `ease-out-quint` for sidebar and drawer.
`prefers-reduced-motion` collapses all durations.

## Components (built)
`Button` (primary/secondary/ghost; sm/md/icon), `Badge` (neutral/accent/warning/
danger), `Kbd`, `Panel`, `PageHeader`, `EmptyState` (honest, names the milestone),
`Spinner`. Shell: `Sidebar` (collapsible to icons with tooltips; mobile drawer),
`Topbar` (breadcrumb, palette trigger, theme toggle, account menu),
`CommandPalette`, `UserMenu`, `BrandMark` (open arc completed by one accent point).

## Interaction
`Mod+K` palette, `Mod+B` sidebar, `G` then a key to navigate (H C T A P S I M K ,).
Visible focus ring everywhere; skip link; Radix handles menu/tooltip a11y.

## Not built yet
Resizable panels, contextual (right-click) menus, toasts, data tables, forms
beyond sign-in. They arrive with the screens that need them.
