import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { StateBadge } from "../components/tasks/StateBadge";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { ApiError } from "../lib/api";
import { formatDuration } from "../lib/format";
import { inspect } from "../lib/inspector";
import { isFinished, tasksApi } from "../lib/tasks";
import type { Task, TaskEvent } from "../lib/tasks";

const n = new Intl.NumberFormat();
const time = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
const ms = (v: number | null) =>
  v == null ? "—" : v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1)} s`;
const count = (v: number | null) => (v == null ? "—" : n.format(v));
const NOTE =
  "Only recorded events are shown. SEED does not store model reasoning, so none is shown.";

function Failure({ error }: { error: Error }) {
  return (
    <div className="flex items-start gap-2 text-sm text-danger" role="alert">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden /> {error.message}
    </div>
  );
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-left text-fg-muted">
          <tr>
            {head.map((h) => (
              <th key={h} className="px-4 py-2 font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums text-fg">{children}</tbody>
      </table>
    </div>
  );
}

const Td = ({ children, wide }: { children: ReactNode; wide?: boolean }) => (
  <td
    className={
      wide
        ? "max-w-[22rem] truncate border-t border-border px-4 py-1.5"
        : "border-t border-border px-4 py-1.5 whitespace-nowrap"
    }
  >
    {children}
  </td>
);

/** Every task, newest first, to pick one to inspect. */
export function InspectorPage() {
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: tasksApi.list, retry: false });
  return (
    <>
      <PageHeader
        title="Inspector"
        description="How a task actually ran: attempts, model steps, tool calls, timing, tokens and checkpoints."
      />
      <Panel title="Tasks">
        {tasks.isPending ? (
          <div className="flex items-center gap-2 px-4 py-6 text-sm text-fg-muted">
            <Spinner /> Loading…
          </div>
        ) : tasks.isError ? (
          <div className="px-4 py-4">
            <Failure error={tasks.error} />
          </div>
        ) : tasks.data.length === 0 ? (
          <EmptyState icon={Activity} title="No executions recorded">
            Every task and chat message is recorded as it runs. Start one, then inspect it here.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {tasks.data.map((t) => (
              <li key={t.id}>
                <Link
                  to={`/inspector/${t.id}`}
                  className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-2"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-fg">{t.title}</p>
                    <p className="truncate text-xs text-fg-muted">
                      {t.model} · {new Date(t.created_at).toLocaleString()}
                    </p>
                  </div>
                  <StateBadge task={t} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <p className="mt-3 text-xs text-fg-subtle">{NOTE}</p>
    </>
  );
}

function Summary({ task, events }: { task: Task; events: TaskEvent[] }) {
  const x = inspect(events);
  const duration =
    task.started_at && (task.finished_at ?? null)
      ? formatDuration((Date.parse(task.finished_at!) - Date.parse(task.started_at)) / 1000)
      : task.started_at
        ? "running"
        : "not started";
  const rows: [string, ReactNode][] = [
    ["Model", task.model],
    ...(task.agent ? [["Agent", task.agent.name] as [string, ReactNode]] : []),
    ...(task.parent_task_id
      ? [
          [
            "Handed over by",
            <Link
              key="parent"
              to={`/inspector/${task.parent_task_id}`}
              className="text-accent hover:underline"
            >
              the task that delegated it
            </Link>,
          ] as [string, ReactNode],
        ]
      : []),
    ["Attempts", `${task.attempt} of ${task.max_attempts}`],
    ["Duration", duration],
    ["Model steps", x.steps.length],
    ["Tool calls", x.tools.length],
    ["Tokens", `${n.format(x.totals.inputTokens)} in / ${n.format(x.totals.outputTokens)} out`],
    ["Time in model", ms(x.totals.modelMs)],
    ["Time in tools", ms(x.totals.toolMs)],
    ["Provider retries", x.totals.retries],
    [
      "Checkpoint",
      task.resumable_from_step == null ? "none" : `after step ${task.resumable_from_step}`,
    ],
    ["Ended", task.termination ?? "—"],
  ];
  return (
    <Panel title="Summary">
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 px-4 py-3 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-fg-muted">{k}</dt>
            <dd className="font-mono tabular-nums text-fg">{v}</dd>
          </div>
        ))}
      </dl>
      {task.error && (
        <p className="border-t border-border px-4 py-2.5 text-xs text-danger">{task.error}</p>
      )}
    </Panel>
  );
}

export function InspectorTaskPage() {
  const { id = "" } = useParams();
  const task = useQuery({
    queryKey: ["task", id],
    queryFn: () => tasksApi.get(id),
    retry: false,
    refetchInterval: (q) => (q.state.data && !isFinished(q.state.data.state) ? 3000 : false),
  });
  const running = task.data !== undefined && !isFinished(task.data.state);
  const events = useQuery({
    queryKey: ["task-events", id],
    queryFn: () => tasksApi.allEvents(id),
    enabled: task.isSuccess,
    retry: false,
    refetchInterval: running ? 3000 : false,
  });

  const back = (
    <Link
      to="/inspector"
      className="mb-3 inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg"
    >
      <ArrowLeft size={13} aria-hidden /> Inspector
    </Link>
  );
  if (task.isError)
    return (
      <>
        {back}
        {task.error instanceof ApiError && task.error.code === "not_found" ? (
          <Panel>
            <EmptyState icon={Activity} title="No such task">
              It may have been deleted with its conversation.
            </EmptyState>
          </Panel>
        ) : (
          <Failure error={task.error} />
        )}
      </>
    );
  if (events.isError) return <Failure error={events.error} />;
  if (task.isPending || events.isPending)
    return (
      <div className="flex items-center gap-2 text-xs text-fg-muted">
        <Spinner /> Loading…
      </div>
    );

  const t = task.data;
  const x = inspect(events.data);
  const visible = events.data.filter((e) => e.type !== "text_delta");
  return (
    <>
      {back}
      <PageHeader
        title={t.title}
        actions={
          <>
            <StateBadge task={t} />
            <Link
              to={t.conversation_id ? `/chat/${t.conversation_id}` : `/tasks/${t.id}`}
              className="text-xs text-accent underline-offset-2 hover:underline"
            >
              {t.conversation_id ? "Open chat" : "Open task"}
            </Link>
          </>
        }
      />
      <div className="flex flex-col gap-4">
        <Summary task={t} events={events.data} />

        <Panel title="Attempts">
          <Table head={["Attempt", "Started", "Worker", "Resumed after step", "Ended", "Outcome"]}>
            {x.attempts.map((a, i) => (
              <tr key={i}>
                <Td>{a.attempt}</Td>
                <Td>{time(a.startedAt)}</Td>
                <Td wide>{a.worker ?? "—"}</Td>
                <Td>{a.resumedAtStep ?? "—"}</Td>
                <Td>{a.endedAt ? time(a.endedAt) : "—"}</Td>
                <Td>{a.outcome ?? (running ? "running" : "—")}</Td>
              </tr>
            ))}
          </Table>
          {x.attempts.length === 0 && (
            <p className="px-4 pb-3 text-xs text-fg-muted">No worker has taken this task yet.</p>
          )}
        </Panel>

        <Panel title="Model steps">
          <Table
            head={["Attempt", "Step", "Model time", "In", "Out", "Finish", "Tool calls", "Retries"]}
          >
            {x.steps.map((s, i) => (
              <tr key={i}>
                <Td>{s.attempt}</Td>
                <Td>
                  {s.step}
                  {s.wrapUp ? " (last, no tools)" : ""}
                </Td>
                <Td>{ms(s.latencyMs)}</Td>
                <Td>{count(s.inputTokens)}</Td>
                <Td>{count(s.outputTokens)}</Td>
                <Td>{s.finishReason ?? "—"}</Td>
                <Td>{s.toolCalls}</Td>
                <Td>{s.retries}</Td>
              </tr>
            ))}
          </Table>
        </Panel>

        <Panel title="Tool calls">
          {x.tools.length === 0 ? (
            <p className="px-4 py-3 text-xs text-fg-muted">This task called no tools.</p>
          ) : (
            <Table head={["Step", "Tool", "Arguments", "Result", "Time", "Approval"]}>
              {x.tools.map((c, i) => (
                <tr key={i}>
                  <Td>{c.step}</Td>
                  <Td>{c.name}</Td>
                  <Td wide>
                    <span title={JSON.stringify(c.args)}>{JSON.stringify(c.args)}</span>
                  </Td>
                  <Td>
                    {c.ok === null ? (
                      "pending"
                    ) : c.ok ? (
                      <span className="text-accent">ok</span>
                    ) : (
                      <span className="text-danger" title={c.error ?? undefined}>
                        {c.errorKind ?? "error"}
                      </span>
                    )}
                  </Td>
                  <Td>{ms(c.durationMs)}</Td>
                  <Td>{c.decision ?? "—"}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>

        {x.delegations.length > 0 && (
          <Panel title="Delegations">
            <Table head={["Agent", "Handed over", "Ended", "Elapsed", "Result"]}>
              {x.delegations.map((d, i) => (
                <tr key={i}>
                  <Td>
                    {d.taskId ? (
                      <Link to={`/inspector/${d.taskId}`} className="text-accent hover:underline">
                        {d.agent}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </Td>
                  <Td>{time(d.startedAt)}</Td>
                  <Td>{d.endedAt ? time(d.endedAt) : "—"}</Td>
                  <Td>
                    {d.endedAt && !d.refused
                      ? ms(Date.parse(d.endedAt) - Date.parse(d.startedAt))
                      : "—"}
                  </Td>
                  <Td wide>
                    <span title={d.refused ?? undefined}>
                      {d.refused ? `refused: ${d.refused}` : (d.state ?? "working")}
                    </span>
                  </Td>
                </tr>
              ))}
            </Table>
          </Panel>
        )}

        <Panel title="Checkpoints">
          {x.checkpoints.length === 0 ? (
            <p className="px-4 py-3 text-xs text-fg-muted">
              None recorded. A checkpoint is saved after each step whose tool results are all in.
            </p>
          ) : (
            <Table head={["Saved", "Attempt", "After step", "Calls waiting"]}>
              {x.checkpoints.map((c) => (
                <tr key={c.seq}>
                  <Td>{time(c.at)}</Td>
                  <Td>{c.attempt}</Td>
                  <Td>{c.steps}</Td>
                  <Td>{c.pending}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>

        <Panel title="Event log">
          <ol className="divide-y divide-border font-mono text-2xs">
            {visible.map((e) => (
              <li key={e.seq} className="flex gap-3 px-4 py-1.5">
                <span className="w-8 shrink-0 text-right text-fg-subtle tabular-nums">{e.seq}</span>
                <span className="shrink-0 text-fg-subtle">{time(e.created_at)}</span>
                <span className="shrink-0 text-fg">{e.type}</span>
                <span className="min-w-0 truncate text-fg-muted" title={JSON.stringify(e.data)}>
                  {JSON.stringify(e.data)}
                </span>
              </li>
            ))}
          </ol>
          {x.textDeltas > 0 && (
            <p className="border-t border-border px-4 py-2 text-xs text-fg-muted">
              {n.format(x.textDeltas)} streamed text chunks are not listed.
            </p>
          )}
        </Panel>
        <p className="text-xs text-fg-subtle">{NOTE}</p>
      </div>
    </>
  );
}
