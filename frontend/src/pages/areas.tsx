import {
  Activity,
  Bot,
  Boxes,
  Cpu,
  FolderKanban,
  ListChecks,
  MessageSquare,
  Wrench,
} from "lucide-react";
import { PlannedPage } from "./Planned";

export const ChatPage = () => (
  <PlannedPage
    title="Chat"
    description="One assistant by default. An entire workforce when necessary."
    icon={MessageSquare}
    emptyTitle="No conversations yet"
    emptyBody="Native chat needs the agent runtime and a configured model provider. Conversations will persist and keep running when you navigate away."
    milestone="M4 · Integrated native chat"
    scope={[
      "Streaming responses with Markdown and code",
      "Attachments and artifact references",
      "Edit, regenerate, and continue sessions",
      "Inline approvals and expandable tool activity",
      "Clear split between replies and durable tasks",
    ]}
  />
);

export const TasksPage = () => (
  <PlannedPage
    title="Tasks"
    description="Durable work that survives refreshes, disconnects, and restarts."
    icon={ListChecks}
    emptyTitle="No tasks"
    emptyBody="Tasks are created from chat once SEED Flow is running. Pause, resume, cancel, and retry will appear only where the execution state supports them."
    milestone="M3 · Durable task infrastructure"
    scope={[
      "Draft, queued, running, waiting, paused, completed, failed, canceled",
      "List, detail, and execution timeline views",
      "Dependencies, checkpoints, and deliverables",
      "Verification results and cost accounting",
    ]}
  />
);

export const AgentsPage = () => (
  <PlannedPage
    title="Agents"
    description="The orchestrator and the specialists it delegates to."
    icon={Bot}
    emptyTitle="No agents defined"
    emptyBody="Agent definitions are configurable, not a fixed workforce. Each specialist runs in its own execution context with explicit inputs, outputs, and completion criteria."
    milestone="M7 · Multi-agent orchestration"
    scope={[
      "Roles, model assignments, and tool permissions",
      "Availability and current workload",
      "Delegation relationships and history",
      "Performance metrics",
    ]}
  />
);

export const ProjectsPage = () => (
  <PlannedPage
    title="Projects"
    description="Related work that stays understandable after weeks away."
    icon={FolderKanban}
    emptyTitle="No projects"
    emptyBody="Projects group conversations, tasks, files, artifacts, repositories, instructions, and knowledge under one scope and permission boundary."
    milestone="M6 · Projects, memory, and artifacts"
    scope={[
      "Overview, milestones, and activity history",
      "Project instructions and knowledge",
      "Files, repositories, and artifacts",
      "Project-specific permissions",
    ]}
  />
);

export const StudioPage = () => (
  <PlannedPage
    title="Studio"
    description="Artifacts SEED produces, with previews and history."
    icon={Boxes}
    emptyTitle="No artifacts"
    emptyBody="Generated HTML and executable content will render in an isolated origin, never inside the privileged workspace."
    milestone="M6 · Projects, memory, and artifacts"
    scope={[
      "Code, HTML apps, documents, data, images, reports",
      "Sandboxed previews",
      "Version history and downloads",
      "Source task and validation status",
    ]}
  />
);

export const InspectorPage = () => (
  <PlannedPage
    title="Inspector"
    description="Observable execution: steps, tools, timing, tokens, and evidence."
    icon={Activity}
    emptyTitle="No executions recorded"
    emptyBody="The inspector shows real execution events and explicit plans. It never fabricates model reasoning."
    milestone="M5 · Command center and inspector"
    scope={[
      "State transitions and tool calls with results",
      "Delegation and model selection",
      "Tokens, cost, errors, and retries",
      "Checkpoints and verification evidence",
    ]}
  />
);

export const ModelsPage = () => (
  <PlannedPage
    title="Models"
    description="Providers, routing, and budgets. Model-agnostic by design."
    icon={Cpu}
    emptyTitle="No providers connected"
    emptyBody="Anthropic, OpenAI, DeepSeek, OpenRouter, OpenAI-compatible, and local endpoints connect through one adapter interface. Credentials are stored server-side and never shown again."
    milestone="M2 · Core agent runtime"
    scope={[
      "Provider connections and model discovery",
      "Defaults and per-agent or per-task overrides",
      "Routing rules and fallback policies",
      "Token budgets, spend limits, and usage",
    ]}
  />
);

export const ToolsPage = () => (
  <PlannedPage
    title="Tools & Skills"
    description="What SEED can do, and under which permissions."
    icon={Wrench}
    emptyTitle="No tools registered"
    emptyBody="Tools are typed: each declares schemas, permissions, timeouts, and limits. Model-generated commands run only in isolated workers, never in the API process."
    milestone="M2 · Core agent runtime"
    scope={[
      "Files, terminal, git, HTTP, web retrieval",
      "Permission and approval policies",
      "Integration status and usage history",
      "Failure diagnostics",
    ]}
  />
);
