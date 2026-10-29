# Roadmap — SEED OS

| M | Name | Scope | State |
|---|---|---|---|
| 0 | Discovery & Foundation | Inspect, environment, architecture, design principles, requirements, roadmap, tooling | Done in Iteration 1 |
| 1 | Premium Application Foundation | Design system, shell, navigation, themes, auth foundation, responsive layouts, page structures; running app | Done; live at seed.nsystems.live |
| 2 | Core Agent Runtime | Provider adapters, conversation loop, tool registry, streaming, lifecycle, errors; real model + tool execution | Done (PR #2); live model comparison in ADR-0007 |
| 3 | Durable Task Infrastructure | Persistent tasks, workers, transitions, checkpoints, cancel, retry, recovery; survive API/worker restarts | In progress: task store, worker, Tasks API (ADR-0008), live SSE with replay and Tasks UI built; Postgres users, revocable sessions, CSRF and audit log built (ADR-0009); sandbox for commands built (ADR-0010) |
| 4 | Integrated Native Chat | Persistent conversations, streaming, task integration, tool activity, approvals, continuation | Not started |
| 5 | Command Center & Inspector | Real metrics, live dashboard, timelines, agent activity, failures, cost | Not started |
| 6 | Projects, Memory, Artifacts | Workspaces, memory, artifact storage, preview, versions | Not started |
| 7 | Multi-Agent Orchestration | Specialists, delegation, worker assignment, routing, agent mgmt | Not started |
| 8 | Integrations & Automation | Gateways, scheduling, notifications, tools, integration mgmt | Not started |
| 9 | Production Hardening | Security review, perf, reliability, a11y, DR, deployment docs, monitoring | Not started |

Milestones may be split. A running, testable app is maintained throughout; backend
integration is not postponed until the frontend is "finished".
Each milestone passes the Directive v1.0 §4 gate on the artifact.
