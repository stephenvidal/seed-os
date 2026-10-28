# Changelog

All notable changes. Format: Keep a Changelog; versions follow the milestones.

## [Unreleased] — M3 Durable tasks (increment 1)
### Added
- Postgres (psycopg 3) with forward-only SQL migrations.
- Durable tasks: state machine, leased workers with heartbeats and fenced writes,
  step checkpoints and resume after a worker crash, dead-letter, graceful
  shutdown, per-task event log (ADR-0008).
- Worker process `python -m seed_api.flow.worker`; compose gains `db` and `worker`.
- Tasks API: create (idempotency key), list, detail, events, cancel, retry.
### Changed
- Cancelling a run now interrupts a provider request that is in flight.

## M2 Core agent runtime
### Added
- Provider interface with typed errors; Ollama adapter (chat, NDJSON streaming,
  tool calls, model list).
- Typed tool registry and per-run workspace file tools (list/read/write).
- Bounded agent loop (steps, time, tokens, tool calls, retries, cancellation).
- `GET /api/v1/models`, `POST /api/v1/runs` (SSE with keepalives).
- Chat page: model picker, streaming answer, expandable tool activity, usage.

## M0/M1, Iteration 1
### Added
- Directive v1.1 (product definition) and docs set: vision, requirements,
  architecture, design system, security, deployment, model strategy, testing,
  roadmap, ADRs 0001–0005.
- SEED API: health, bootstrap sign-in with signed session cookie, server-side
  role guard, login rate limit, typed errors, real host telemetry.
- SEED Workspace: design tokens (light/dark/system), app shell, collapsible
  sidebar and mobile drawer, command palette, keyboard navigation, Command
  Center with live telemetry, Settings, honest empty states for unbuilt areas.
- Docker Compose stack (api + web/nginx with security headers).
- CI and build-and-deploy workflows for the self-hosted golden-eye runner,
  production compose file (adapted from dustline; deploy off by default).
