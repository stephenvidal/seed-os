import { request } from "./api";

/** A procedure the owner saved (D-033), in the shape of a Hermes Agent SKILL.md. */
export type Skill = {
  id: string;
  owner: string;
  /** Private to this agent; null: shared with SEED and the agents allowed it. */
  agent_id: string | null;
  name: string;
  description: string;
  tags: string[];
  body: string;
  /** The task that last wrote it, with your approval; null: you did. */
  written_by_task: string | null;
  created_at: string;
  updated_at: string;
};

export type SkillInput = Pick<Skill, "name" | "description" | "tags" | "body" | "agent_id">;

export type Imported = {
  skill: Skill;
  /** Header keys SEED does not act on. */
  ignored: string[];
};

/** One SKILL.md of a Hermes skills folder, and what importing it does or did (D-043). */
export type FolderItem = {
  path: string;
  name: string | null;
  description: string | null;
  outcome: "new" | "imported" | "name_taken" | "invalid";
  error: string | null;
};

export type FolderFile = { path: string; text: string };

export const SKILLS = ["skills"] as const;

/** The rule the API applies to a name, so the form can say so before sending. */
export const SKILL_NAME = /^[a-z0-9][a-z0-9-]{0,63}$/;

export const skillsApi = {
  list: () => request<Skill[]>("/api/v1/skills"),
  create: (body: SkillInput) =>
    request<Skill>("/api/v1/skills", { method: "POST", body: JSON.stringify(body) }),
  /** Replaces the whole skill. */
  update: (id: string, body: SkillInput) =>
    request<Skill>(`/api/v1/skills/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  remove: (id: string) => request<void>(`/api/v1/skills/${id}`, { method: "DELETE" }),
  /** The text of a SKILL.md. */
  import: (text: string, agentId: string | null) =>
    request<Imported>("/api/v1/skills/import", {
      method: "POST",
      body: JSON.stringify({ text, agent_id: agentId }),
    }),
  /** Every SKILL.md of a Hermes skills folder; `preview` saves nothing. */
  importFolder: (files: FolderFile[], agentId: string | null, preview: boolean) =>
    request<FolderItem[]>(`/api/v1/skills/import-folder${preview ? "?preview=true" : ""}`, {
      method: "POST",
      body: JSON.stringify({ files, agent_id: agentId }),
    }),
};
