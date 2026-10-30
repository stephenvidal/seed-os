/** Client for notifications (/api/v1/notifications, D-030). */
import { request } from "./api";

export type Notification = {
  id: string;
  kind: "task_completed" | "task_failed" | "approval_needed" | "schedule_skipped";
  title: string;
  body: string;
  task_id: string | null;
  schedule_id: string | null;
  created_at: string;
  read_at: string | null;
};

export type NotificationList = {
  /** Every unread notification, not only those in `items`. */
  unread: number;
  items: Notification[];
};

export const NOTIFICATIONS = ["notifications"] as const;

/** Where a notification leads: its task, or the schedules page. */
export function notificationLink(n: Notification): string {
  if (n.kind === "schedule_skipped" || !n.task_id) return "/schedules";
  return `/tasks/${n.task_id}`;
}

export const notificationsApi = {
  list: (limit = 20) => request<NotificationList>(`/api/v1/notifications?limit=${limit}`),
  read: (id: string) => request<void>(`/api/v1/notifications/${id}/read`, { method: "POST" }),
  readAll: () => request<void>("/api/v1/notifications/read-all", { method: "POST" }),
};
