# Roadmap — SEED OS

| M | Name | Scope | State |
|---|---|---|---|
| 0 | Discovery & Foundation | Inspect, environment, architecture, design principles, requirements, roadmap, tooling | Done in Iteration 1 |
| 1 | Premium Application Foundation | Design system, shell, navigation, themes, auth foundation, responsive layouts, page structures; running app | Done; live at seed.nsystems.live |
| 2 | Core Agent Runtime | Provider adapters, conversation loop, tool registry, streaming, lifecycle, errors; real model + tool execution | Done (PR #2); live model comparison in ADR-0007 |
| 3 | Durable Task Infrastructure | Persistent tasks, workers, transitions, checkpoints, cancel, retry, recovery; survive API/worker restarts | Done: task store, worker, Tasks API (ADR-0008), live SSE with replay and Tasks UI; Postgres users, revocable sessions, CSRF and audit log (ADR-0009); sandbox for commands (ADR-0010) |
| 4 | Integrated Native Chat | Persistent conversations, streaming, task integration, tool activity, approvals, continuation | In progress: saved conversations whose turns run as tasks, live replies, Markdown (ADR-0011); approvals for commands (ADR-0012); rename, delete and search (D-010); edit and regenerate as kept versions (ADR-0013). Saved files link from the answer and open in a dialog (D-021). Remaining: attachments |
| 5 | Command Center & Inspector | Real metrics, live dashboard, timelines, agent activity, failures, cost | In progress: live Command Center from the task store (D-012); Execution Inspector from the event log (D-013). Next: spend from published Ollama prices and the balance API (D-014). Agent activity: per-agent tasks and tokens (M7) |
| 6 | Projects, Memory, Artifacts | Workspaces, memory, artifact storage, preview, versions | Built: every changed file saved as a version after each run, restored after a sandbox restart (ADR-0014); Studio with versions, downloads and sandboxed HTML previews (ADR-0015). Projects with instructions, chats and files (D-017). Project memory proposed by the agent and approved by the owner (D-018). Searchable project knowledge (D-021). Session summaries of turns older than the chat window (D-022). Tasks in projects (D-023). |
| 7 | Multi-Agent Orchestration | Specialists, delegation, worker assignment, routing, agent mgmt | In progress: agent definitions with starter specialists (D-024); delegation as separate tasks that report back (D-025); parallel sub-tasks with parallel, per-task and depth limits, and several tasks per worker (D-026); delegation views in chat, the Inspector and the Command Center (links, hand-off table, agent activity). Remaining: workload and routing views, agent metrics beyond tokens |
| 8 | Integrations & Automation | Gateways, scheduling, notifications, tools, integration mgmt | In progress: the Tools & Skills page lists real tools, policies and usage (D-028). Schedules API and worker (D-029) and the Schedules page. Notifications and the bell (D-030). Next: gateways |
| 9 | Production Hardening | Security review, perf, reliability, a11y, DR, deployment docs, monitoring | Not started |

Milestones may be split. A running, testable app is maintained throughout; backend
integration is not postponed until the frontend is "finished".
Each milestone passes the Directive v1.0 §4 gate on the artifact.
