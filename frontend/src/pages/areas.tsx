import { Bot, Boxes, Cpu, FolderKanban, Wrench } from "lucide-react";
import { PlannedPage } from "./Planned";

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
