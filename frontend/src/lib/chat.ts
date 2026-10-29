/** Client for saved conversations (/api/v1/conversations). Each turn is a task. */
import { request } from "./api";
import type { Task, TaskState } from "./tasks";

export type Conversation = {
  id: string;
  owner: string;
  title: string;
  model: string;
  project_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ConversationSummary = Conversation & { turns: number; last_state: TaskState | null };
/** A turn on the shown path, with the ids of that message's versions, oldest first. */
export type Turn = Task & { versions: string[] };
export type ConversationDetail = { conversation: Conversation; turns: Turn[] };

export const chatApi = {
  /** With `query`, only conversations whose title, messages or answers contain it. */
  list: (query = "") =>
    request<ConversationSummary[]>(
      `/api/v1/conversations?limit=200${query ? `&q=${encodeURIComponent(query)}` : ""}`,
    ),
  inProject: (projectId: string) =>
    request<ConversationSummary[]>(`/api/v1/conversations?limit=200&project_id=${projectId}`),
  get: (id: string) => request<ConversationDetail>(`/api/v1/conversations/${id}`),
  /** The key makes a double-submitted message count once. */
  start: (body: { model: string; prompt: string; project_id?: string }, idempotencyKey: string) =>
    request<ConversationDetail>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  /** A new version of a message: edited with `prompt`, asked again without. */
  addVersion: (
    id: string,
    turnId: string,
    body: { prompt?: string; model?: string },
    idempotencyKey: string,
  ) =>
    request<Task>(`/api/v1/conversations/${id}/turns/${turnId}/versions`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  /** Show another version of a message, with its newest replies. */
  show: (id: string, turnId: string) =>
    request<ConversationDetail>(`/api/v1/conversations/${id}/shown`, {
      method: "PUT",
      body: JSON.stringify({ turn_id: turnId }),
    }),
  rename: (id: string, title: string) =>
    request<Conversation>(`/api/v1/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  /** Into a project, or out of one with null; applies from the next message. */
  move: (id: string, projectId: string | null) =>
    request<Conversation>(`/api/v1/conversations/${id}/project`, {
      method: "PUT",
      body: JSON.stringify({ project_id: projectId }),
    }),
  /** Deletes the conversation with all its turns; refused while one is unfinished. */
  remove: (id: string) => request<void>(`/api/v1/conversations/${id}`, { method: "DELETE" }),
  send: (id: string, body: { prompt: string; model?: string }, idempotencyKey: string) =>
    request<Task>(`/api/v1/conversations/${id}/turns`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
};
