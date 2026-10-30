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
};
