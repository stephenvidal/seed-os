import { request } from "./api";

/** Tools an agent may be allowed (D-024), in the order the API keeps them. */
export const AGENT_TOOLS = [
  { name: "list_files", label: "List files" },
  { name: "read_file", label: "Read files" },
  { name: "write_file", label: "Write files" },
  {
    name: "run_command",
    label: "Run commands",
    note: "needs the sandbox; asks you first by default",
  },
  { name: "search_knowledge", label: "Search project knowledge", note: "in projects only" },
] as const;

export type AgentTool = (typeof AGENT_TOOLS)[number]["name"];

export type Agent = {
  id: string;
  owner: string;
  name: string;
  /** What the agent is for; SEED reads it to choose whom to delegate to. */
  description: string;
  instructions: string;
  /** null: the model of the task that delegates. */
  model: string | null;
  tools: AgentTool[];
  created_at: string;
  updated_at: string;
};

export type AgentInput = Pick<Agent, "name" | "description" | "instructions" | "model" | "tools">;

export const AGENTS = ["agents"] as const;

export const agentsApi = {
  list: () => request<Agent[]>("/api/v1/agents"),
  create: (body: AgentInput) =>
    request<Agent>("/api/v1/agents", { method: "POST", body: JSON.stringify(body) }),
  /** Replaces the whole definition. */
  update: (id: string, body: AgentInput) =>
    request<Agent>(`/api/v1/agents/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  remove: (id: string) => request<void>(`/api/v1/agents/${id}`, { method: "DELETE" }),
};
