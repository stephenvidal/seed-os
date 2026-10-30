import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BarChart3, Sparkles } from "lucide-react";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { ApiError } from "../lib/api";
import { TOOLS, toolsApi } from "../lib/tools";
import type { ToolInfo, ToolUsage, ToolsView } from "../lib/tools";

const n = new Intl.NumberFormat();
const ms = (v: number | null) =>
  v == null ? "—" : v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1)} s`;

const PERMISSION: Record<ToolInfo["permission"], string> = {
  read: "reads",
  write: "writes",
  network: "network",
  exec: "runs code",
};

function ToolRow({ tool }: { tool: ToolInfo }) {
  return (
    <li>
      <details className="group">
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 hover:bg-surface-2">
          <span className="font-mono text-sm text-fg">{tool.name}</span>
          <Badge>{PERMISSION[tool.permission]}</Badge>
          <Badge tone={tool.requires_approval ? "warning" : "neutral"}>
            {tool.requires_approval ? "asks you first" : "runs on its own"}
          </Badge>
          {tool.deferred && <Badge>answered by an agent</Badge>}
          <span className="font-mono text-xs text-fg-muted">
            {tool.timeout_s} s · {n.format(tool.max_output_chars)} chars
          </span>
          <span className="basis-full text-xs text-fg-muted sm:basis-0 sm:flex-1">
            {tool.available_in}
          </span>
        </summary>
        <div className="flex flex-col gap-3 border-t border-border px-4 py-3 text-xs">
          <p className="text-fg-muted whitespace-pre-wrap">{tool.description}</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-fg-muted">Time limit</dt>
            <dd className="font-mono text-fg">{tool.timeout_s} s per call</dd>
            <dt className="text-fg-muted">Output kept</dt>
            <dd className="font-mono text-fg">{n.format(tool.max_output_chars)} characters</dd>
            <dt className="text-fg-muted">Offered in</dt>
            <dd className="text-fg">{tool.available_in}</dd>
          </dl>
          <table className="w-full">
            <thead className="text-left text-fg-muted">
              <tr>
                <th className="pb-1 font-medium">Argument</th>
                <th className="pb-1 font-medium">Type</th>
                <th className="pb-1 font-medium">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {tool.arguments.map((a) => (
                <tr key={a.name} className="border-t border-border align-top">
                  <td className="py-1 pr-3 font-mono text-fg">
                    {a.name}
                    {a.required ? "" : " (optional)"}
                  </td>
                  <td className="py-1 pr-3 font-mono text-fg-muted">{a.type}</td>
                  <td className="py-1 text-fg-muted">{a.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </li>
  );
}

function UsageTable({ data }: { data: ToolsView }) {
  if (data.usage === null)
    return (
      <EmptyState icon={BarChart3} title="Usage needs a database">
        Tool results are recorded with tasks. Set SEED_DATABASE_URL to keep them.
      </EmptyState>
    );
  if (data.usage.length === 0)
    return (
      <EmptyState icon={BarChart3} title="No tool calls recorded">
        Nothing has used a tool in the last {data.window_hours} hours.
      </EmptyState>
    );
  return (
    <ul aria-label="Tool usage" className="divide-y divide-border">
      {data.usage.map((u) => (
        <UsageRow key={u.tool} u={u} />
      ))}
    </ul>
  );
}

function UsageRow({ u }: { u: ToolUsage }) {
  const kinds = Object.entries(u.failures)
    .map(([kind, count]) => `${kind.replace("_", " ")} ${count}`)
    .join(", ");
  const stats: [string, string, boolean?][] = [
    ["Calls", n.format(u.calls)],
    ["Succeeded", n.format(u.ok)],
    ["Failed", n.format(u.failed), u.failed > 0],
    ["Average time", ms(u.avg_ms)],
  ];
  return (
    <li className="flex flex-col gap-1.5 px-4 py-3 text-xs">
      <span className="font-mono text-sm text-fg">{u.tool}</span>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        {stats.map(([label, value, bad]) => (
          <div key={label}>
            <dt className="text-fg-muted">{label}</dt>
            <dd className={`font-mono tabular-nums ${bad ? "text-danger" : "text-fg"}`}>{value}</dd>
          </div>
        ))}
      </dl>
      {u.failed > 0 && (
        <div className="text-fg-muted">
          <p>Why they failed: {kinds || "—"}</p>
          {u.reasons.length > 0 && (
            <ul aria-label={`${u.tool} errors`} className="mt-1 flex flex-col gap-0.5">
              {u.reasons.map((r) => (
                <li key={r.message} className="break-words">
                  <span className="font-mono tabular-nums text-fg">{n.format(r.count)}×</span>{" "}
                  {r.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

export function ToolsPage() {
  const view = useQuery({ queryKey: TOOLS, queryFn: () => toolsApi.get(), retry: false });
  const body = view.isPending ? (
    <div className="flex items-center gap-2 px-4 py-6 text-sm text-fg-muted">
      <Spinner /> Loading…
    </div>
  ) : view.isError ? (
    <div className="flex items-start gap-2 px-4 py-4 text-sm text-danger" role="alert">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
      {view.error instanceof ApiError ? view.error.message : "Unexpected error."}
    </div>
  ) : null;
  const data = view.data;
  const asking = data?.tools.filter((t) => t.requires_approval).map((t) => t.name) ?? [];

  return (
    <>
      <PageHeader
        title="Tools & Skills"
        description="What SEED can do, and under which permissions. Commands never run in the API process: they run in an isolated sandbox."
      />
      <div className="flex flex-col gap-4">
        <Panel title="Tools">
          {body ??
            (data && (
              <ul aria-label="Tools" className="divide-y divide-border">
                {data.tools.map((t) => (
                  <ToolRow key={t.name} tool={t} />
                ))}
              </ul>
            ))}
        </Panel>
        {data && (
          <>
            <Panel title="Approval policy">
              <p className="px-4 py-3 text-xs text-fg-muted">
                {asking.length === 0
                  ? "No tool waits for approval: every call runs on its own."
                  : `A task pauses for your approval before each call to ${asking.join(", ")}.`}{" "}
                This is set by SEED_APPROVAL_REQUIRED_TOOLS on the server.
              </p>
            </Panel>
            <Panel title={`Usage (${data.window_hours}h)`}>
              <UsageTable data={data} />
            </Panel>
          </>
        )}
        <Panel title="Skills">
          <EmptyState icon={Sparkles} title="No skills yet">
            Skills are not built. Tools are what SEED can use today.
          </EmptyState>
        </Panel>
      </div>
    </>
  );
}
