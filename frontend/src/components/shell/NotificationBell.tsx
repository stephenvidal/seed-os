import * as Menu from "@radix-ui/react-dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bell, CalendarClock, CheckCircle2, Hand, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { NOTIFICATIONS, notificationLink, notificationsApi } from "../../lib/notifications";
import type { Notification } from "../../lib/notifications";

const POLL_MS = 30_000;

const KIND: Record<Notification["kind"], { icon: LucideIcon; label: string; tone: string }> = {
  task_completed: { icon: CheckCircle2, label: "Finished", tone: "text-accent" },
  task_failed: { icon: XCircle, label: "Failed", tone: "text-danger" },
  approval_needed: { icon: Hand, label: "Needs your approval", tone: "text-warning" },
  schedule_skipped: { icon: CalendarClock, label: "Schedule skipped a run", tone: "text-fg-muted" },
};

const ago = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });

export function NotificationBell() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const list = useQuery({
    queryKey: NOTIFICATIONS,
    queryFn: () => notificationsApi.list(),
    refetchInterval: POLL_MS,
    retry: false,
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: NOTIFICATIONS });
  const read = useMutation({ mutationFn: notificationsApi.read, onSuccess: refresh });
  const readAll = useMutation({ mutationFn: notificationsApi.readAll, onSuccess: refresh });
  const unread = list.data?.unread ?? 0;

  function open(n: Notification) {
    if (!n.read_at) read.mutate(n.id);
    void navigate(notificationLink(n));
  }

  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        className="relative grid h-8 w-8 place-items-center rounded-control text-fg-muted outline-none hover:bg-surface-3 hover:text-fg focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Bell size={16} aria-hidden />
        {unread > 0 && (
          <span
            aria-hidden
            className="absolute right-0.5 top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 text-[10px] font-semibold leading-none text-accent-fg"
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content
          align="end"
          sideOffset={6}
          className="z-50 flex max-h-[min(28rem,80vh)] w-[min(22rem,calc(100vw-2rem))] flex-col rounded-panel border border-border bg-surface-1 shadow-pop"
        >
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <p className="flex-1 text-sm font-medium text-fg">Notifications</p>
            {unread > 0 && (
              <Menu.Item
                className="cursor-default rounded-[5px] px-1.5 py-0.5 text-xs text-accent outline-none data-[highlighted]:bg-surface-3"
                onSelect={(e) => {
                  e.preventDefault();
                  readAll.mutate();
                }}
              >
                Mark all read
              </Menu.Item>
            )}
          </div>
          <div className="overflow-y-auto p-1">
            {list.isPending ? (
              <p className="px-2 py-3 text-xs text-fg-muted">Loading…</p>
            ) : list.isError ? (
              <p role="alert" className="flex items-start gap-1.5 px-2 py-3 text-xs text-danger">
                <AlertTriangle size={14} className="mt-px shrink-0" aria-hidden />
                {list.error instanceof ApiError ? list.error.message : "Unexpected error."}
              </p>
            ) : list.data.items.length === 0 ? (
              <p className="px-2 py-3 text-xs text-fg-muted">
                Nothing yet. You will hear here when a task finishes, fails or needs your approval,
                and when a schedule skips a run.
              </p>
            ) : (
              list.data.items.map((n) => {
                const kind = KIND[n.kind];
                return (
                  <Menu.Item
                    key={n.id}
                    onSelect={() => open(n)}
                    className="flex cursor-default gap-2 rounded-[5px] px-2 py-2 outline-none data-[highlighted]:bg-surface-3"
                  >
                    <kind.icon size={14} className={`mt-0.5 shrink-0 ${kind.tone}`} aria-hidden />
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="flex items-center gap-1.5 text-xs text-fg-muted">
                        {kind.label} · {ago(n.created_at)}
                        {!n.read_at && (
                          <span className="ml-auto h-1.5 w-1.5 rounded-full bg-accent">
                            <span className="sr-only">unread</span>
                          </span>
                        )}
                      </span>
                      <span className="break-words text-sm text-fg">{n.title}</span>
                      {n.body && (
                        <span className="line-clamp-2 break-words text-xs text-fg-muted">
                          {n.body}
                        </span>
                      )}
                    </span>
                  </Menu.Item>
                );
              })
            )}
          </div>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
