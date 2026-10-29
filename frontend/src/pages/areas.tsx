import { Bot, Cpu, Wrench } from "lucide-react";
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
