import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Inbox,
  ListChecks,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { useSession } from "../lib/auth";
import { formatBytes, formatDuration } from "../lib/format";
import { useSystem } from "./useSystem";

function greeting(d = new Date()): string {
  const h = d.getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

type ComponentState = {
  name: string;
  detail: string;
  state: "online" | "not-built";
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
  {
    name: "SEED Core",
    detail: "Agent runtime, providers, tools",
    state: "not-built",
    milestone: "M2",
  },
  { name: "SEED Flow", detail: "Durable tasks and workers", state: "not-built", milestone: "M3" },
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

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-4">
          <Panel title="Needs attention" action={<Badge>0</Badge>}>
            <EmptyState icon={ShieldCheck} title="Nothing waiting on you">
              Approvals, failed tasks, and questions from SEED will collect here.
            </EmptyState>
          </Panel>
          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="In progress">
              <EmptyState icon={CircleDashed} title="No active work" milestone="M3">
                Running and queued tasks appear here with live progress.
              </EmptyState>
            </Panel>
            <Panel title="Recently completed">
              <EmptyState icon={Inbox} title="No completed work yet" milestone="M3">
                Finished tasks and their deliverables land here.{" "}
                <Link to="/tasks" className="text-accent underline-offset-2 hover:underline">
                  View tasks
                </Link>
              </EmptyState>
            </Panel>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <Panel title="System health" action={<Badge tone="accent">Live</Badge>}>
            <SystemHealth />
          </Panel>
          <Panel title="Platform components">
            <ul className="divide-y divide-border">
              {COMPONENTS.map((c) => (
                <li key={c.name} className="flex items-center gap-3 px-4 py-2.5">
                  {c.state === "online" ? (
                    <CheckCircle2 size={14} className="shrink-0 text-accent" aria-label="Online" />
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
