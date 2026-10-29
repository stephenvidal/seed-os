/** Client for the tool catalog and usage (/api/v1/tools), read from the worker's tools. */
import { request } from "./api";

export type ToolArgument = { name: string; type: string; required: boolean; description: string };

export type ToolInfo = {
  name: string;
  description: string;
  permission: "read" | "write" | "network" | "exec";
  timeout_s: number;
  max_output_chars: number;
  /** A person approves each call first. */
  requires_approval: boolean;
  /** The result comes from another task (delegation), not from running here. */
  deferred: boolean;
  available_in: string;
  arguments: ToolArgument[];
};

export type ToolUsage = {
  tool: string;
  calls: number;
  ok: number;
  failed: number;
  avg_ms: number | null;
  failures: Record<string, number>;
};

export type ToolsView = {
  window_hours: number;
  tools: ToolInfo[];
  /** Null when no database is configured: nothing is recorded. */
  usage: ToolUsage[] | null;
};

export const TOOLS = ["tools"] as const;

export const toolsApi = {
  get: (hours = 24) => request<ToolsView>(`/api/v1/tools?hours=${hours}`),
};
