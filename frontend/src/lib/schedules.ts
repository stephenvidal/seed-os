/** Client for schedules (/api/v1/schedules, D-029): saved tasks the workers start when due. */
import { request } from "./api";

export const MIN_EVERY_MINUTES = 5;
export const MAX_EVERY_MINUTES = 10080;

export type Schedule = {
  id: string;
  owner: string;
  name: string;
  prompt: string;
  model: string;
  project_id: string | null;
  kind: "interval" | "daily";
  every_minutes: number | null;
  /** "HH:MM:SS" in `timezone`. */
  at_time: string | null;
  timezone: string;
  enabled: boolean;
  /** Null while the schedule is paused. */
  next_run_at: string | null;
  last_run_at: string | null;
  last_outcome: "started" | "skipped_busy" | null;
  last_task_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ScheduleInput = Pick<
  Schedule,
  | "name"
  | "prompt"
  | "model"
  | "project_id"
  | "kind"
  | "every_minutes"
  | "at_time"
  | "timezone"
  | "enabled"
>;

export const SCHEDULES = ["schedules"] as const;

/** The timetable in words: "Every 2 hours", "Daily at 09:30 (Europe/Paris)". */
export function describeTimetable(
  s: Pick<Schedule, "kind" | "every_minutes" | "at_time" | "timezone">,
): string {
  if (s.kind === "daily") return `Daily at ${(s.at_time ?? "").slice(0, 5)} (${s.timezone})`;
  const m = s.every_minutes ?? 0;
  if (m % 1440 === 0) return m === 1440 ? "Every day" : `Every ${m / 1440} days`;
  if (m % 60 === 0) return m === 60 ? "Every hour" : `Every ${m / 60} hours`;
  return `Every ${m} minutes`;
}

export const schedulesApi = {
  list: () => request<Schedule[]>("/api/v1/schedules"),
  create: (body: ScheduleInput) =>
    request<Schedule>("/api/v1/schedules", { method: "POST", body: JSON.stringify(body) }),
  /** Replaces the whole definition. */
  update: (id: string, body: ScheduleInput) =>
    request<Schedule>(`/api/v1/schedules/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  remove: (id: string) => request<void>(`/api/v1/schedules/${id}`, { method: "DELETE" }),
  /** Starts the task now without moving the timetable. */
  run: (id: string) =>
    request<{ task_id: string }>(`/api/v1/schedules/${id}/run`, { method: "POST" }),
};
