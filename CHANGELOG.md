# Changelog

All notable changes. Format: Keep a Changelog; versions follow the milestones.

## [Unreleased] — M0/M1, Iteration 1
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
