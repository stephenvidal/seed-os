import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Database,
  ListChecks,
  RotateCcw,
  Square,
  XCircle,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AgentTaskLinks } from "../components/tasks/AgentTaskLinks";
import { ApprovalPrompt } from "../components/tasks/ApprovalPrompt";
import { StateBadge } from "../components/tasks/StateBadge";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Markdown } from "../components/ui/Markdown";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { ApiError, api } from "../lib/api";
import { PROJECTS, projectsApi } from "../lib/projects";
import {
  delegatedTasks,
  followTask,
  isFinished,
  pendingApproval,
  tasksApi,
  toTimeline,
} from "../lib/tasks";
import type { Task, TaskEvent, TimelineItem, Verification } from "../lib/tasks";

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

const tokens = (t: Task) =>
  t.usage.input_tokens + t.usage.output_tokens
    ? `${t.usage.input_tokens} in / ${t.usage.output_tokens} out tokens`
    : null;

function Unavailable({ error }: { error: Error }) {
  const noDb = error instanceof ApiError && error.code === "database_not_configured";
  return (
    <Panel>
      <EmptyState
        icon={noDb ? Database : AlertTriangle}
        title={noDb ? "Tasks need a database" : "Tasks unavailable"}
      >
        {error.message}
      </EmptyState>
    </Panel>
  );
}

function NewTask() {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models, retry: false });
  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("");
  const [check, setCheck] = useState("");
  const projects = useQuery({ queryKey: PROJECTS, queryFn: projectsApi.list, retry: false });
  // A project's page links here with ?project=<id> to start a task in it.
  const [params] = useSearchParams();
  const [project, setProject] = useState(params.get("project") ?? "");
  // One key per intended task: resubmitting after a network error cannot duplicate it.
  const key = useRef(crypto.randomUUID());
  const navigate = useNavigate();
  const qc = useQueryClient();
  const selected = model || models.data?.default_model || models.data?.models[0]?.id || "";
  const create = useMutation({
    mutationFn: () =>
      tasksApi.create(
        {
          model: selected,
          prompt: prompt.trim(),
          ...(project && { project_id: project }),
          ...(check.trim() && { check: check.trim() }),
        },
        key.current,
      ),
    onSuccess: (task) => {
      key.current = crypto.randomUUID();
      setPrompt("");
      setCheck("");
      void qc.invalidateQueries({ queryKey: ["tasks"] });
      void navigate(`/tasks/${task.id}`);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (prompt.trim() && selected && !create.isPending) create.mutate();
  };

  return (
    <Panel title="New task">
      <form onSubmit={submit} className="flex flex-col gap-3 p-4">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          maxLength={20000}
          aria-label="What should SEED do?"
          placeholder="What should SEED do? It keeps working if you close this page."
          className="resize-y rounded-control border border-border bg-surface-1 px-3 py-2.5 text-sm text-fg outline-none placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-ring"
        />
        <label className="flex flex-col gap-1 text-xs text-fg-muted">
          Check (optional): a command run in the task&apos;s files when SEED says it is done. Exit
          code 0 passes; anything else fails the task.
          <input
            value={check}
            onChange={(e) => {
              setCheck(e.target.value);
              key.current = crypto.randomUUID(); // a different task now
            }}
            maxLength={8000}
            placeholder="e.g. python -m pytest -q"
            className="h-8 rounded-control border border-border bg-surface-1 px-2 font-mono text-xs text-fg outline-none placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-ring"
          />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex min-w-0 items-center gap-2 text-xs text-fg-muted">
            Model
            <select
              value={selected}
              onChange={(e) => setModel(e.target.value)}
              disabled={!models.data}
              className="h-8 max-w-48 min-w-0 rounded-control border border-border bg-surface-1 px-2 font-mono text-xs text-fg"
            >
              {models.isPending && <option>Loading…</option>}
              {models.data?.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.id}
                </option>
              ))}
            </select>
          </label>
          {(projects.data?.length || project) && (
            <label className="flex min-w-0 items-center gap-2 text-xs text-fg-muted">
              Project
              <select
                value={project}
                onChange={(e) => {
                  setProject(e.target.value);
                  key.current = crypto.randomUUID(); // a different task now
                }}
                className="h-8 max-w-48 min-w-0 rounded-control border border-border bg-surface-1 px-2 text-xs text-fg"
              >
                <option value="">None</option>
                {projects.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Button
            type="submit"
            variant="primary"
            className="ml-auto"
            disabled={!prompt.trim() || !selected || create.isPending}
          >
            {create.isPending ? "Creating…" : "Create task"}
          </Button>
        </div>
        {models.isError && (
          <p role="alert" className="text-xs text-danger">
            {models.error.message}
          </p>
        )}
        {create.isError && (
          <p role="alert" className="text-xs text-danger">
            {create.error.message}
          </p>
        )}
      </form>
    </Panel>
  );
}

export function TasksPage() {
  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: tasksApi.list,
    retry: false,
    // Poll only while something is still moving.
    refetchInterval: (q) => (q.state.data?.some((t) => !isFinished(t.state)) ? 3000 : false),
  });

  return (
    <>
      <PageHeader
        title="Tasks"
        description="Durable work: it keeps running when you close the page, and survives worker and server restarts."
      />
      {tasks.isError ? (
        <Unavailable error={tasks.error} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="self-start lg:order-2">
            <NewTask />
          </div>
          <Panel title="All tasks" className="min-w-0 self-start lg:order-1">
            {tasks.isPending ? (
              <div className="flex items-center gap-2 p-4 text-xs text-fg-muted">
                <Spinner /> Loading…
              </div>
            ) : tasks.data.length === 0 ? (
              <EmptyState icon={ListChecks} title="No tasks yet">
                Describe what you want done. SEED runs it in the background and records every step.
              </EmptyState>
            ) : (
              <ul className="divide-y divide-border">
                {tasks.data.map((t) => (
                  <li key={t.id}>
                    <Link
                      to={`/tasks/${t.id}`}
                      className="flex flex-col gap-1 px-4 py-3 hover:bg-surface-2 focus-visible:bg-surface-2"
                    >
                      <span className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-fg">
                          {t.title}
                        </span>
                        <StateBadge task={t} />
                      </span>
                      <span className="flex flex-wrap gap-x-3 font-mono text-2xs text-fg-subtle">
                        <span>{when(t.created_at)}</span>
                        <span>{t.model}</span>
                        {t.attempt > 1 && <span>attempt {t.attempt}</span>}
                        {tokens(t) && <span>{tokens(t)}</span>}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}

function StepView({
  item,
  interrupted,
}: {
  item: TimelineItem & { kind: "step" };
  interrupted: boolean;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-control border border-border bg-surface-2 px-3 py-2.5">
      <p className="flex items-center gap-2 font-mono text-2xs text-fg-subtle">
        Step {item.step}
        {item.attempt > 1 && ` · attempt ${item.attempt}`}
        {item.tokens && ` · ${item.tokens.input} in / ${item.tokens.output} out`}
        {interrupted && <Badge tone="warning">interrupted</Badge>}
        {!item.done && !interrupted && <Spinner label="Working" />}
      </p>
      {item.tools.map((t) => (
        <div key={t.id} className="text-xs">
          <div className="flex items-center gap-2">
            {t.ok === undefined ? (
              interrupted ? (
                <AlertTriangle size={13} className="text-warning" aria-label="No result" />
              ) : (
                <Spinner label="Running tool" />
              )
            ) : t.ok ? (
              <CheckCircle2 size={13} className="text-accent" aria-label="Succeeded" />
            ) : (
              <XCircle size={13} className="text-danger" aria-label="Failed" />
            )}
            <span className="font-mono font-medium text-fg">{t.name}</span>
            {t.durationMs !== undefined && (
              <span className="ml-auto font-mono text-fg-subtle">{t.durationMs} ms</span>
            )}
          </div>
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all font-mono text-2xs text-fg-muted">
            {JSON.stringify(t.args)}
          </pre>
          {t.error && <p className="mt-1 text-danger">{t.error}</p>}
        </div>
      ))}
      {item.text && <p className="text-sm leading-6 whitespace-pre-wrap text-fg">{item.text}</p>}
    </div>
  );
}

const NOTE_DOT = {
  neutral: "bg-border-strong",
  accent: "bg-accent",
  warning: "bg-warning",
  danger: "bg-danger",
} as const;

function Timeline({ items, live }: { items: TimelineItem[]; live: boolean }) {
  if (!items.length) return <p className="px-4 py-3 text-xs text-fg-muted">No events yet.</p>;
  return (
    <ol className="flex flex-col gap-2 p-4">
      {items.map((item, i) =>
        item.kind === "note" ? (
          <li key={item.seq} className="flex items-baseline gap-2.5 text-xs">
            <span
              className={`h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full ${NOTE_DOT[item.tone]}`}
            />
            <span className="text-fg">{item.text}</span>
            <time className="ml-auto shrink-0 font-mono text-2xs text-fg-subtle" dateTime={item.at}>
              {new Date(item.at).toLocaleTimeString()}
            </time>
          </li>
        ) : (
          <li key={item.seq}>
            <StepView item={item} interrupted={!item.done && (i < items.length - 1 || !live)} />
          </li>
        ),
      )}
    </ol>
  );
}

/** One task's page. Keyed by id: moving between tasks (a link to an agent's task or
 * back to its parent) must not carry the earlier task's events over. */
export function TaskDetailPage() {
  const { id = "" } = useParams();
  return <TaskDetail key={id} />;
}

function TaskDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const task = useQuery({ queryKey: ["task", id], queryFn: () => tasksApi.get(id), retry: false });
  const projects = useQuery({
    queryKey: PROJECTS,
    queryFn: projectsApi.list,
    retry: false,
    enabled: Boolean(task.data?.project_id),
  });
  const parentId = task.data?.parent_task_id ?? null;
  const parent = useQuery({
    queryKey: ["task", parentId],
    queryFn: () => tasksApi.get(parentId ?? ""),
    retry: false,
    enabled: parentId !== null,
  });
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const lastSeq = useRef(0);
  // Set once the server ends the stream: every event of the finished task has arrived.
  // A cancel can finish a queued task before its event does, so the task's state
  // alone cannot close the stream.
  const [ended, setEnded] = useState(false);
  const state = task.data?.state;
  const following = state !== undefined && !ended;
  const live = state !== undefined && !isFinished(state);

  useEffect(() => {
    if (!following) return;
    const stop = followTask(
      id,
      lastSeq.current,
      (e) => {
        if (e.seq <= lastSeq.current) return;
        lastSeq.current = e.seq;
        setEvents((prev) => [...prev, e]);
        if (e.type !== "text_delta") void qc.invalidateQueries({ queryKey: ["task", id] });
      },
      () => {
        setEnded(true);
        void qc.invalidateQueries({ queryKey: ["task", id] });
        void qc.invalidateQueries({ queryKey: ["tasks"] });
      },
    );
    return stop;
  }, [id, following, qc]);

  const act = useMutation({
    mutationFn: (action: "cancel" | "retry") =>
      action === "cancel" ? tasksApi.cancel(id) : tasksApi.retry(id),
    onSuccess: (t) => {
      qc.setQueryData(["task", id], t);
      if (!isFinished(t.state)) setEnded(false); // a retried task is followed again
      void qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  if (task.isError)
    return task.error instanceof ApiError && task.error.code === "not_found" ? (
      <Panel>
        <EmptyState icon={ListChecks} title="No such task">
          <Link to="/tasks" className="text-accent underline-offset-2 hover:underline">
            Back to tasks
          </Link>
        </EmptyState>
      </Panel>
    ) : (
      <Unavailable error={task.error} />
    );
  if (task.isPending)
    return (
      <div className="flex items-center gap-2 text-xs text-fg-muted">
        <Spinner /> Loading…
      </div>
    );

  const t = task.data;
  const timeline = toTimeline(events);
  const asking = pendingApproval(events);
  const agents = delegatedTasks(events);
  return (
    <>
      <Link
        to="/tasks"
        className="mb-3 inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg"
      >
        <ArrowLeft size={13} aria-hidden /> Tasks
      </Link>
      <PageHeader
        title={t.title}
        actions={
          <>
            <StateBadge task={t} />
            {!isFinished(t.state) && (
              <Button
                size="sm"
                onClick={() => act.mutate("cancel")}
                disabled={act.isPending || t.cancel_requested}
              >
                <Square size={12} aria-hidden /> Cancel
              </Button>
            )}
            {(t.state === "failed" || t.state === "canceled") && (
              <Button size="sm" onClick={() => act.mutate("retry")} disabled={act.isPending}>
                <RotateCcw size={12} aria-hidden /> Retry
              </Button>
            )}
          </>
        }
      />
      {act.isError && (
        <p role="alert" className="-mt-3 mb-4 text-xs text-danger">
          {act.error.message}
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-4">
          {asking && (
            <ApprovalPrompt
              key={asking.id}
              taskId={t.id}
              call={asking}
              onDecided={() => void qc.invalidateQueries({ queryKey: ["task", id] })}
            />
          )}
          {t.state === "completed" && t.result_text && (
            <Panel title="Result">
              <div className="px-4 py-3">
                <Markdown text={t.result_text} toggle />
              </div>
            </Panel>
          )}
          {t.check_command && <CheckPanel command={t.check_command} result={t.verification} />}
          {t.termination === "check_failed" && t.result_text && (
            <Panel title="What SEED said (its check did not agree)">
              <div className="px-4 py-3">
                <Markdown text={t.result_text} toggle />
              </div>
            </Panel>
          )}
          {t.state === "failed" && (
            <Panel title="Failure">
              <p role="alert" className="flex items-start gap-2 px-4 py-3 text-sm text-danger">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden />
                {t.error ?? t.termination ?? "Failed"}
              </p>
            </Panel>
          )}
          {agents.length > 0 && (
            <Panel title="Handed to agents">
              <AgentTaskLinks agents={agents} className="px-4 py-3" />
            </Panel>
          )}
          <Panel title="Timeline" action={live ? <Badge tone="accent">live</Badge> : undefined}>
            <Timeline items={timeline} live={live} />
          </Panel>
        </div>
        <Panel title="Details" className="h-fit">
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 px-4 py-3 text-xs">
            <dt className="text-fg-muted">Model</dt>
            <dd className="truncate font-mono text-fg">{t.model}</dd>
            <dt className="text-fg-muted">Attempt</dt>
            <dd className="font-mono text-fg">
              {t.attempt} of {t.max_attempts}
            </dd>
            <dt className="text-fg-muted">Tokens</dt>
            <dd className="font-mono text-fg">{tokens(t) ?? "—"}</dd>
            {t.project_id && !t.conversation_id && (
              <>
                <dt className="text-fg-muted">Project</dt>
                <dd className="truncate">
                  <Link to={`/projects/${t.project_id}`} className="text-accent hover:underline">
                    {projects.data?.find((p) => p.id === t.project_id)?.name ?? "Open project"}
                  </Link>
                </dd>
              </>
            )}
            {t.agent && (
              <>
                <dt className="text-fg-muted">Agent</dt>
                <dd className="truncate text-fg">{t.agent.name}</dd>
              </>
            )}
            {parentId && (
              <>
                <dt className="text-fg-muted">Handed over by</dt>
                <dd className="truncate">
                  <Link to={`/tasks/${parentId}`} className="text-accent hover:underline">
                    {parent.data?.title ?? "the task that delegated it"}
                  </Link>
                </dd>
              </>
            )}
            <dt className="text-fg-muted">Created</dt>
            <dd className="text-fg">{when(t.created_at)}</dd>
            {t.finished_at && (
              <>
                <dt className="text-fg-muted">Finished</dt>
                <dd className="text-fg">{when(t.finished_at)}</dd>
              </>
            )}
          </dl>
          <div className="border-t border-border px-4 py-3">
            <p className="mb-1 text-xs text-fg-muted">Prompt</p>
            <p className="text-sm whitespace-pre-wrap break-words text-fg">{t.prompt}</p>
          </div>
        </Panel>
      </div>
    </>
  );
}

function CheckPanel({ command, result }: { command: string; result?: Verification | null }) {
  const output = result ? [result.stdout, result.stderr].filter(Boolean).join("\n") : "";
  return (
    <Panel
      title="Check"
      action={
        result ? (
          <Badge tone={result.passed ? "accent" : "danger"}>
            {result.passed ? "passed" : "failed"}
          </Badge>
        ) : (
          <Badge>not run yet</Badge>
        )
      }
    >
      <div className="flex flex-col gap-2 px-4 py-3 text-xs">
        <code className="font-mono break-all text-fg">{command}</code>
        {result && (
          <p className="text-fg-muted">
            {result.timed_out
              ? "Ran out of time"
              : result.exit_code === null
                ? "Could not be run"
                : `Exit code ${result.exit_code}`}{" "}
            · {(result.duration_ms / 1000).toFixed(1)} s
          </p>
        )}
        {output && (
          <pre className="max-h-64 overflow-auto rounded-control bg-surface-2 p-2 font-mono whitespace-pre-wrap break-words text-fg">
            {output}
          </pre>
        )}
      </div>
    </Panel>
  );
}
