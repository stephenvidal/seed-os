import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  Bot,
  CheckCircle2,
  CircleDashed,
  Database,
  Inbox,
  ListChecks,
  ShieldCheck,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { StateBadge } from "../components/tasks/StateBadge";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { useSession } from "../lib/auth";
import { ApiError } from "../lib/api";
import { formatBytes, formatDuration } from "../lib/format";
import { overviewApi } from "../lib/overview";
import type { Overview } from "../lib/overview";
import type { Task } from "../lib/tasks";
import { useSystem } from "./useSystem";

const REFRESH_MS = 10_000;
const n = new Intl.NumberFormat();

/** Where a task is best followed: its conversation for a chat turn, else its page. */
const taskHref = (t: Task) => (t.conversation_id ? `/chat/${t.conversation_id}` : `/tasks/${t.id}`);

function ago(iso: string, now: string): string {
  const s = Math.max(0, (Date.parse(now) - Date.parse(iso)) / 1000);
  return s < 60 ? "just now" : `${formatDuration(s).split(" ")[0]} ago`;
}

function TaskRow({ task, children }: { task: Task; children?: ReactNode }) {
  return (
    <li>
      <Link
        to={taskHref(task)}
        className="flex items-start gap-3 px-4 py-2.5 hover:bg-surface-2 focus-visible:bg-surface-2"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-fg">{task.title}</p>
          {children && <div className="mt-0.5 truncate text-xs text-fg-muted">{children}</div>}
        </div>
        <StateBadge task={task} />
      </Link>
    </li>
  );
}

function Stats({ data }: { data: Overview }) {
  const c = data.counts;
  const tiles: [string, number, string?][] = [
    ["Running", c.running],
    ["Queued", c.queued],
    ["Need you", c.waiting, c.waiting ? "text-warning" : undefined],
    [`Completed (${data.window_hours}h)`, c.completed],
    [`Failed (${data.window_hours}h)`, c.failed, c.failed ? "text-danger" : undefined],
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {tiles.map(([label, value, tone]) => (
        <div key={label} className="rounded-panel border border-border bg-surface-1 px-4 py-3">
          <dt className="text-xs text-fg-muted">{label}</dt>
          <dd className={`mt-1 font-mono text-xl tabular-nums ${tone ?? "text-fg"}`}>
            {n.format(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function AgentTable({ data }: { data: Overview }) {
  if (data.agents.length === 0)
    return (
      <EmptyState icon={Bot} title="No agent work yet">
        When SEED hands part of a job to an agent, what each one is doing appears here.
      </EmptyState>
    );
  return (
    <div className="overflow-x-auto px-4 py-3">
      <table className="w-full text-xs">
        <thead className="text-left text-fg-muted">
          <tr>
            <th className="pb-2 font-medium">Agent</th>
            <th className="pb-2 text-right font-medium">Working</th>
            <th className="pb-2 text-right font-medium">Completed</th>
            <th className="pb-2 text-right font-medium">Failed</th>
            <th className="pb-2 text-right font-medium">Canceled</th>
            <th className="pb-2 text-right font-medium">Tokens</th>
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums text-fg">
          {data.agents.map((a) => (
            <tr key={a.name} className="border-t border-border">
              <td className="py-1.5 pr-3 break-all">{a.name}</td>
              <td className="py-1.5 text-right">{n.format(a.working)}</td>
              <td className="py-1.5 text-right">{n.format(a.completed)}</td>
              <td className={`py-1.5 text-right ${a.failed ? "text-danger" : ""}`}>
                {n.format(a.failed)}
              </td>
              <td className="py-1.5 text-right">{n.format(a.canceled)}</td>
              <td className="py-1.5 text-right">{n.format(a.input_tokens + a.output_tokens)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UsageTable({ data }: { data: Overview }) {
  if (data.usage.length === 0)
    return (
      <EmptyState icon={BarChart3} title="No model use yet">
        Token counts appear here once tasks finish.
      </EmptyState>
    );
  return (
    <div className="overflow-x-auto px-4 py-3">
      <table className="w-full text-xs">
        <thead className="text-left text-fg-muted">
          <tr>
            <th className="pb-2 font-medium">Model</th>
            <th className="pb-2 text-right font-medium">Tasks</th>
            <th className="pb-2 text-right font-medium">In tokens</th>
            <th className="pb-2 text-right font-medium">Out tokens</th>
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums text-fg">
          {data.usage.map((u) => (
            <tr key={u.model} className="border-t border-border">
              <td className="py-1.5 pr-3 break-all">{u.model}</td>
              <td className="py-1.5 text-right">{n.format(u.tasks)}</td>
              <td className="py-1.5 text-right">{n.format(u.input_tokens)}</td>
              <td className="py-1.5 text-right">{n.format(u.output_tokens)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-2xs text-fg-subtle">
        Spend is not shown: no model prices are configured.
      </p>
    </div>
  );
}

function WorkPanels() {
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: () => overviewApi.get(),
    refetchInterval: REFRESH_MS,
    retry: false,
  });
  if (overview.isPending)
    return (
      <div className="flex items-center gap-2 px-1 py-6 text-sm text-fg-muted">
        <Spinner /> Reading tasks…
      </div>
    );
  if (overview.isError)
    return overview.error instanceof ApiError &&
      overview.error.code === "database_not_configured" ? (
      <Panel>
        <EmptyState icon={Database} title="Tasks need a database">
          {overview.error.message}
        </EmptyState>
      </Panel>
    ) : (
      <div className="flex items-start gap-2 px-1 py-4 text-sm text-danger" role="alert">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
        {overview.error.message}
      </div>
    );

  const data = overview.data;
  const attention = data.counts.waiting + data.counts.failed;
  return (
    <>
      <Stats data={data} />
      <Panel
        title="Needs attention"
        action={<Badge tone={attention ? "warning" : "neutral"}>{attention}</Badge>}
      >
        {data.attention.length === 0 ? (
          <EmptyState icon={ShieldCheck} title="Nothing waiting on you">
            Commands waiting for approval and tasks that failed in the last {data.window_hours}{" "}
            hours collect here.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {data.attention.map((t) => (
              <TaskRow key={t.id} task={t}>
                {t.awaiting_approval
                  ? `Wants to run ${t.awaiting_approval.name}`
                  : (t.error ?? "Failed")}
              </TaskRow>
            ))}
          </ul>
        )}
      </Panel>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Panel title="In progress">
          {data.active.length === 0 ? (
            <EmptyState icon={CircleDashed} title="No active work">
              Running and queued tasks appear here.
            </EmptyState>
          ) : (
            <ul className="divide-y divide-border">
              {data.active.map((t) => (
                <TaskRow key={t.id} task={t}>
                  {t.agent ? `${t.agent.name} · ` : ""}
                  {t.model} · started {ago(t.started_at ?? t.created_at, data.generated_at)}
                </TaskRow>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="Recently completed">
          {data.recent.length === 0 ? (
            <EmptyState icon={Inbox} title="No completed work yet">
              Tasks finished in the last {data.window_hours} hours land here.{" "}
              <Link to="/tasks" className="text-accent underline-offset-2 hover:underline">
                View tasks
              </Link>
            </EmptyState>
          ) : (
            <ul className="divide-y divide-border">
              {data.recent.map((t) => (
                <TaskRow key={t.id} task={t}>
                  {t.model} · {n.format(t.usage.input_tokens + t.usage.output_tokens)} tokens ·{" "}
                  {ago(t.finished_at ?? t.updated_at, data.generated_at)}
                </TaskRow>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <Panel title={`Agent activity (${data.window_hours}h)`}>
        <AgentTable data={data} />
      </Panel>
      <Panel title={`Model usage (${data.window_hours}h)`}>
        <UsageTable data={data} />
      </Panel>
    </>
  );
}

function greeting(d = new Date()): string {
  const h = d.getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

type ComponentState = {
  name: string;
  detail: string;
  /** online: answering now; built: shipped but not health-checked here; not-built. */
  state: "online" | "built" | "not-built";
  milestone?: string;
};

function SystemHealth() {
  const { data, isPending, isError, error } = useSystem();

  if (isPending)
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-sm text-fg-muted">
        <Spinner /> Reading host telemetry…
      </div>
    );
  if (isError)
    return (
      <div className="flex items-start gap-2 px-4 py-4 text-sm text-danger" role="alert">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden /> {error.message}
      </div>
    );

  const used =
    data.memory_total_bytes && data.memory_available_bytes != null
      ? data.memory_total_bytes - data.memory_available_bytes
      : null;
  const pct = used != null && data.memory_total_bytes ? used / data.memory_total_bytes : null;
  const rows: [string, string][] = [
    ["Uptime", formatDuration(data.uptime_seconds)],
    [
      "Load (1m)",
      data.load_average ? `${data.load_average[0].toFixed(2)} / ${data.cpu_count} CPU` : "—",
    ],
    ["API memory", formatBytes(data.process_rss_bytes)],
    ["Version", `v${data.version} · Python ${data.python}`],
  ];

  return (
    <div className="px-4 py-3">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-fg-muted">Host memory</span>
        <span className="font-mono tabular-nums text-fg">
          {formatBytes(used)}{" "}
          <span className="text-fg-subtle">/ {formatBytes(data.memory_total_bytes)}</span>
        </span>
      </div>
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3"
        role="meter"
        aria-label="Host memory in use"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct != null ? Math.round(pct * 100) : undefined}
      >
        <div
          className={pct != null && pct > 0.9 ? "h-full bg-danger" : "h-full bg-accent"}
          style={{ width: `${Math.round((pct ?? 0) * 100)}%` }}
        />
      </div>
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-fg-muted">{k}</dt>
            <dd className="text-right font-mono tabular-nums text-fg">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

const COMPONENTS: ComponentState[] = [
  { name: "SEED API", detail: "Authentication, telemetry", state: "online" },
  { name: "SEED Core", detail: "Agent runtime, providers, tools", state: "built" },
  { name: "SEED Flow", detail: "Durable tasks and workers", state: "built" },
  {
    name: "SEED Memory",
    detail: "Projects, knowledge, artifacts",
    state: "not-built",
    milestone: "M6",
  },
];

export function CommandCenterPage() {
  const { data: me } = useSession();
  return (
    <>
      <PageHeader
        title={`${greeting()}${me ? `, ${me.username}` : ""}`}
        description="What is happening, what needs your attention, and what has been accomplished."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-4">
          <WorkPanels />
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <Panel title="System health" action={<Badge tone="accent">Live</Badge>}>
            <SystemHealth />
          </Panel>
          <Panel title="Platform components">
            <ul className="divide-y divide-border">
              {COMPONENTS.map((c) => (
                <li key={c.name} className="flex items-center gap-3 px-4 py-2.5">
                  {c.state === "online" ? (
                    <CheckCircle2 size={14} className="shrink-0 text-accent" aria-label="Online" />
                  ) : c.state === "built" ? (
                    <CheckCircle2
                      size={14}
                      className="shrink-0 text-fg-subtle"
                      aria-label="Built"
                    />
                  ) : (
                    <ListChecks
                      size={14}
                      className="shrink-0 text-fg-subtle"
                      aria-label="Not built"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-fg">{c.name}</p>
                    <p className="truncate text-xs text-fg-muted">{c.detail}</p>
                  </div>
                  {c.state === "online" ? (
                    <Badge tone="accent">Online</Badge>
                  ) : c.state === "built" ? (
                    <Badge>Built</Badge>
                  ) : (
                    <Badge>{c.milestone}</Badge>
                  )}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </>
  );
}
