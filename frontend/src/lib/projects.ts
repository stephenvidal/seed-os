/** Client for projects (/api/v1/projects): chats grouped under shared instructions. */
import { request } from "./api";

export type Project = {
  id: string;
  owner: string;
  name: string;
  /** Sent to the model with every message in the project. */
  instructions: string;
  created_at: string;
  updated_at: string;
  conversations: number;
  /** Memory notes the agent proposed that wait for the owner. */
  proposed_memories: number;
};

export type Memory = {
  id: string;
  project_id: string;
  content: string;
  /** Only approved notes reach the model. */
  status: "proposed" | "approved";
  /** "agent", or the owner who wrote it. */
  created_by: string;
  source_task_id: string | null;
  source_conversation_id: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
};

export const MAX_NOTE_CHARS = 500;
export const memoryKey = (projectId: string) => ["memory", projectId] as const;

export const PROJECTS = ["projects"] as const;
export const projectKey = (id: string) => ["project", id] as const;

export const projectsApi = {
  list: () => request<Project[]>("/api/v1/projects"),
  get: (id: string) => request<Project>(`/api/v1/projects/${id}`),
  create: (body: { name: string; instructions?: string }) =>
    request<Project>("/api/v1/projects", { method: "POST", body: JSON.stringify(body) }),
  /** New instructions reach the model from the next message sent. */
  update: (id: string, body: { name?: string; instructions?: string }) =>
    request<Project>(`/api/v1/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  /** The project's chats are kept and leave the project. */
  remove: (id: string) => request<void>(`/api/v1/projects/${id}`, { method: "DELETE" }),
};

const notes = (projectId: string) => `/api/v1/projects/${projectId}/memories`;

/** Project memory: proposals first, then approved notes. */
export const memoryApi = {
  list: (projectId: string) => request<Memory[]>(notes(projectId)),
  /** The owner's own note, approved as written. */
  add: (projectId: string, content: string) =>
    request<Memory>(notes(projectId), { method: "POST", body: JSON.stringify({ content }) }),
  update: (projectId: string, id: string, body: { content?: string; approve?: boolean }) =>
    request<Memory>(`${notes(projectId)}/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  /** Deletes a note, or rejects a proposal. */
  remove: (projectId: string, id: string) =>
    request<void>(`${notes(projectId)}/${id}`, { method: "DELETE" }),
};
