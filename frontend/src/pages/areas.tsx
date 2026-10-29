import { Cpu } from "lucide-react";
import { PlannedPage } from "./Planned";

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
