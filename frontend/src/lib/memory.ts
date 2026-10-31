/** Memory about the owner (D-040): notes SEED is given in every one of its runs. */
import { request } from "./api";

export type OwnerNote = {
  id: string;
  owner: string;
  content: string;
  /** Only approved notes reach the model. */
  status: "proposed" | "approved";
  /** "agent", or the owner who wrote it. */
  created_by: string;
  source_task_id: string | null;
  source_conversation_id: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
};

export const OWNER_MEMORY = ["owner-memory"] as const;

/** Proposals first, then approved notes. */
export const ownerMemoryApi = {
  list: () => request<OwnerNote[]>("/api/v1/memory"),
  add: (content: string) =>
    request<OwnerNote>("/api/v1/memory", { method: "POST", body: JSON.stringify({ content }) }),
  update: (id: string, body: { content?: string; approve?: boolean }) =>
    request<OwnerNote>(`/api/v1/memory/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  remove: (id: string) => request<void>(`/api/v1/memory/${id}`, { method: "DELETE" }),
};
