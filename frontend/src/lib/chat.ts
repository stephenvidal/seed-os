/** Client for saved conversations (/api/v1/conversations). Each turn is a task. */
import { request } from "./api";
import type { Task, TaskState } from "./tasks";

export type Conversation = {
  id: string;
  owner: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
};

export type ConversationSummary = Conversation & { turns: number; last_state: TaskState | null };
export type ConversationDetail = { conversation: Conversation; turns: Task[] };

export const chatApi = {
  list: () => request<ConversationSummary[]>("/api/v1/conversations?limit=200"),
  get: (id: string) => request<ConversationDetail>(`/api/v1/conversations/${id}`),
  /** The key makes a double-submitted message count once. */
  start: (body: { model: string; prompt: string }, idempotencyKey: string) =>
    request<ConversationDetail>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  send: (id: string, body: { prompt: string; model?: string }, idempotencyKey: string) =>
    request<Task>(`/api/v1/conversations/${id}/turns`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
};
