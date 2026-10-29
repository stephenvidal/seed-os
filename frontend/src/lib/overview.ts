/** Client for the Command Center's overview (/api/v1/overview), read from tasks. */
import { request } from "./api";
import type { Task } from "./tasks";

export type ModelUsage = {
  model: string;
  tasks: number;
  input_tokens: number;
  output_tokens: number;
};

export type Overview = {
  window_hours: number;
  generated_at: string;
  /** queued/running/waiting are now; the rest finished within the window. */
  counts: {
    queued: number;
    running: number;
    /** Waiting for a person's approval. */
    waiting: number;
    /** Waiting for a task they delegated to an agent. */
    delegating: number;
    completed: number;
    failed: number;
    canceled: number;
  };
  /** Waiting for approval, then failed within the window. */
  attention: Task[];
  /** Running, then queued. */
  active: Task[];
  /** Completed within the window, newest first. */
  recent: Task[];
  /** Tokens of tasks finished within the window, by model. */
  usage: ModelUsage[];
};

export const overviewApi = {
  get: (hours = 24) => request<Overview>(`/api/v1/overview?hours=${hours}`),
};
