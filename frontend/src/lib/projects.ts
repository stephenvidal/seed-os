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
};

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
