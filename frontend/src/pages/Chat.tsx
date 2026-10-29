import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  ChevronRight,
  Cpu,
  ListChecks,
  MessageSquare,
  Plus,
  RotateCcw,
  Square,
  Wrench,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApprovalPrompt } from "../components/tasks/ApprovalPrompt";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Markdown } from "../components/ui/Markdown";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { cn } from "../components/ui/cn";
import { ApiError, api } from "../lib/api";
import { chatApi } from "../lib/chat";
import type { ConversationDetail } from "../lib/chat";
import { followTask, isFinished, pendingApproval, tasksApi, toTimeline } from "../lib/tasks";
import type { Task, TaskEvent, TimelineItem, ToolActivity } from "../lib/tasks";

const CONVERSATIONS = ["conversations"] as const;
const conversationKey = (id: string) => ["conversation", id] as const;

const STOPPED: Record<string, string> = {
  max_steps: "Stopped: step limit reached.",
  deadline: "Stopped: time limit reached.",
  token_budget: "Stopped: token budget reached.",
  provider_error: "Stopped: model provider error.",
  abandoned: "The worker stopped responding on every attempt.",
};

function ToolList({ tools, live }: { tools: ToolActivity[]; live: boolean }) {
  const [open, setOpen] = useState(false);
  if (!tools.length) return null;
  return (
    <div className="rounded-control border border-border bg-surface-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex h-8 w-full items-center gap-2 px-2.5 text-xs text-fg-muted hover:text-fg"
      >
        <ChevronRight
          size={14}
          className={cn("transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <Wrench size={13} aria-hidden />
        Used {tools.length} tool{tools.length === 1 ? "" : "s"}
        {tools.some((t) => t.ok === false) && <Badge tone="warning">some failed</Badge>}
      </button>
      {open && (
        <ul className="divide-y divide-border border-t border-border">
          {tools.map((t) => (
            <li key={t.id} className="px-3 py-2 text-xs">
              <div className="flex items-center gap-2">
                {t.ok === undefined ? (
                  live ? (
                    <Spinner label="Running tool" />
                  ) : (
                    <AlertTriangle size={13} className="text-warning" aria-label="No result" />
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
              <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap break-all font-mono text-2xs text-fg-muted">
                {JSON.stringify(t.args)}
              </pre>
              {t.error && <p className="mt-1 text-danger">{t.error}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const steps = (items: TimelineItem[]) =>
  items.filter((i): i is TimelineItem & { kind: "step" } => i.kind === "step");

/** A turn still being answered: follows its task's live event stream. */
function LiveReply({ task, onEnd }: { task: Task; onEnd: () => void }) {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const lastSeq = useRef(0);

  useEffect(
    () =>
      followTask(
        task.id,
        lastSeq.current,
        (e) => {
          if (e.seq <= lastSeq.current) return;
          lastSeq.current = e.seq;
          setEvents((prev) => [...prev, e]);
          // The conversation list marks chats that need you.
          if (e.type === "approval_requested") onEnd();
        },
        onEnd,
      ),
    [task.id, onEnd],
  );

  const s = steps(toTimeline(events));
  // Each step's text replaces the one before: the last step carries the answer.
  const text = s.at(-1)?.text ?? "";
  const tools = s.flatMap((x) => x.tools);
  const resumed = events.some((e) => e.type === "attempt_started" && e.attempt > 1);
  const asking = pendingApproval(events);
  return (
    <div className="flex flex-col gap-2">
      {resumed && (
        <p className="text-xs text-warning">Resumed on another attempt after an interruption.</p>
      )}
      <ToolList tools={tools} live />
      {text && <Markdown text={text} />}
      {asking && (
        <ApprovalPrompt key={asking.id} taskId={task.id} call={asking} onDecided={onEnd} />
      )}
      {!text && !asking && (
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          <Spinner />
          {task.state === "queued" && !s.length ? "Waiting for a worker…" : "Working…"}
        </div>
      )}
    </div>
  );
}

/** A finished turn's tool activity, loaded only when asked for. */
function PastActivity({ task }: { task: Task }) {
  const [open, setOpen] = useState(false);
  const events = useQuery({
    queryKey: ["task-events", task.id],
    queryFn: () => tasksApi.events(task.id),
    enabled: open,
    staleTime: Infinity,
  });
  if (open && events.data) {
    const tools = steps(toTimeline(events.data.events)).flatMap((x) => x.tools);
    return tools.length ? (
      <ToolList tools={tools} live={false} />
    ) : (
      <p className="text-xs text-fg-subtle">No tools used.</p>
    );
  }
  return (
    <button
      type="button"
      onClick={() => setOpen(true)}
      className="flex w-fit items-center gap-1.5 text-xs text-fg-subtle hover:text-fg"
    >
      {open ? <Spinner label="Loading activity" /> : <Wrench size={12} aria-hidden />}
      Show activity
    </button>
  );
}

function TurnView({
  task,
  last,
  onEnd,
  onRetry,
  retrying,
}: {
  task: Task;
  last: boolean;
  onEnd: () => void;
  onRetry: () => void;
  retrying: boolean;
}) {
  const finished = isFinished(task.state);
  const tokens = task.usage.input_tokens + task.usage.output_tokens;
  return (
    <div className="flex flex-col gap-3">
      <div className="ml-auto max-w-[80%] rounded-panel bg-surface-3 px-3.5 py-2.5 text-sm whitespace-pre-wrap break-words text-fg">
        {task.prompt}
      </div>
      {!finished ? (
        <LiveReply task={task} onEnd={onEnd} />
      ) : (
        <div className="flex flex-col gap-2">
          <PastActivity task={task} />
          {task.state === "completed" && <Markdown text={task.result_text ?? ""} />}
          {task.state === "failed" && (
            <p role="alert" className="flex items-start gap-2 text-xs text-danger">
              <AlertTriangle size={14} className="mt-px shrink-0" aria-hidden />
              {task.error ?? STOPPED[task.termination ?? ""] ?? "The answer failed."}
            </p>
          )}
          {task.state === "canceled" && <p className="text-xs text-fg-muted">Stopped.</p>}
          <div className="flex items-center gap-3 font-mono text-2xs text-fg-subtle">
            <span>{task.model}</span>
            {tokens > 0 && (
              <span>
                {task.usage.input_tokens} in / {task.usage.output_tokens} out tokens
              </span>
            )}
            <Link to={`/tasks/${task.id}`} className="hover:text-fg">
              Task
            </Link>
            {last && (task.state === "failed" || task.state === "canceled") && (
              <button
                type="button"
                onClick={onRetry}
                disabled={retrying}
                className="flex items-center gap-1 font-sans text-xs text-fg-muted hover:text-fg"
              >
                <RotateCcw size={12} aria-hidden /> Try again
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Composer({
  onSend,
  onStop,
  busy,
  model,
  models,
  onModel,
  disabled,
}: {
  onSend: (text: string) => Promise<unknown>;
  onStop?: () => void;
  busy: boolean;
  model: string;
  models: string[] | undefined;
  onModel: (m: string) => void;
  disabled: boolean;
}) {
  const [prompt, setPrompt] = useState("");
  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    const text = prompt.trim();
    if (!text || busy || disabled || !model) return;
    setPrompt("");
    try {
      await onSend(text);
    } catch {
      setPrompt(text); // keep the message so it can be sent again
    }
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };
  return (
    <form onSubmit={submit} className="mt-3 flex flex-col gap-2">
      <div className="flex items-end gap-2">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          maxLength={20000}
          placeholder="Describe what you want done…  (Enter to send, Shift+Enter for a new line)"
          aria-label="Message"
          className="min-h-[52px] flex-1 resize-none rounded-panel border border-border bg-surface-1 px-3.5 py-3 text-sm text-fg outline-none placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-ring"
        />
        {onStop ? (
          <Button
            variant="secondary"
            size="icon"
            className="h-[52px] w-[52px]"
            onClick={onStop}
            aria-label="Stop"
          >
            <Square size={16} />
          </Button>
        ) : (
          <Button
            type="submit"
            variant="primary"
            size="icon"
            className="h-[52px] w-[52px]"
            disabled={!prompt.trim() || !model || busy || disabled}
            aria-label="Send"
          >
            <ArrowUp size={18} />
          </Button>
        )}
      </div>
      <label className="flex items-center gap-2 self-end text-xs text-fg-muted">
        Model
        <select
          value={model}
          onChange={(e) => onModel(e.target.value)}
          disabled={!models}
          className="h-7 max-w-56 rounded-control border border-border bg-surface-1 px-2 font-mono text-xs text-fg"
        >
          {!models && <option>Loading…</option>}
          {models?.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
    </form>
  );
}

function useModels() {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models, retry: false });
  const ids = models.data?.models.map((m) => m.id);
  const fallback = models.data?.default_model ?? ids?.[0] ?? "";
  return { models, ids, fallback };
}

function errorText(err: unknown) {
  return err instanceof ApiError ? err.message : "Unexpected error.";
}

function NewConversation() {
  const { ids, fallback } = useModels();
  const [model, setModel] = useState("");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const start = useMutation({
    mutationFn: (prompt: string) =>
      chatApi.start({ model: model || fallback, prompt }, crypto.randomUUID()),
    onSuccess: (detail) => {
      qc.setQueryData(conversationKey(detail.conversation.id), detail);
      void qc.invalidateQueries({ queryKey: CONVERSATIONS });
      navigate(`/chat/${detail.conversation.id}`);
    },
  });
  return (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-panel border border-border bg-surface-1">
        <EmptyState icon={MessageSquare} title="Ask SEED to do something">
          Every message runs as a task in the background, so the answer keeps coming if you leave
          and is saved with the conversation. SEED can answer directly, work with files in this
          conversation&apos;s workspace and run commands in its sandbox. Each tool call is shown
          with its arguments and result.
        </EmptyState>
      </div>
      {start.isError && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {errorText(start.error)}
        </p>
      )}
      <Composer
        onSend={(t) => start.mutateAsync(t)}
        busy={start.isPending}
        model={model || fallback}
        models={ids}
        onModel={setModel}
        disabled={false}
      />
    </>
  );
}

function ConversationView({ id }: { id: string }) {
  const qc = useQueryClient();
  const { ids } = useModels();
  const detail = useQuery({
    queryKey: conversationKey(id),
    queryFn: () => chatApi.get(id),
    retry: false,
  });
  const [model, setModel] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const turns = detail.data?.turns ?? [];
  const lastTurn = turns.at(-1);
  const answering = lastTurn !== undefined && !isFinished(lastTurn.state);
  const current = model || detail.data?.conversation.model || "";

  // Stable, because LiveReply reconnects its stream whenever onEnd changes.
  const refresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: conversationKey(id) });
    void qc.invalidateQueries({ queryKey: CONVERSATIONS });
  }, [qc, id]);
  const send = useMutation({
    mutationFn: (prompt: string) =>
      chatApi.send(
        id,
        current !== detail.data?.conversation.model ? { prompt, model: current } : { prompt },
        crypto.randomUUID(),
      ),
    onSuccess: (task) => {
      qc.setQueryData<ConversationDetail>(conversationKey(id), (d) =>
        d ? { ...d, turns: [...d.turns, task] } : d,
      );
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: ({ task, action }: { task: Task; action: "cancel" | "retry" }) =>
      action === "cancel" ? tasksApi.cancel(task.id) : tasksApi.retry(task.id),
    onSettled: refresh,
  });

  // Braces matter: Chromium's scrollIntoView returns a Promise, and an effect that
  // returns a non-function crashes React on cleanup.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns.length]);

  if (detail.isError)
    return detail.error instanceof ApiError && detail.error.code === "not_found" ? (
      <Panel>
        <EmptyState icon={MessageSquare} title="No such conversation">
          <Link to="/chat" className="text-accent underline-offset-2 hover:underline">
            Start a new one
          </Link>
        </EmptyState>
      </Panel>
    ) : (
      <Unavailable error={detail.error} />
    );
  if (detail.isPending)
    return (
      <div className="flex items-center gap-2 text-xs text-fg-muted">
        <Spinner /> Loading…
      </div>
    );

  const failure = send.error ?? act.error;
  return (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-panel border border-border bg-surface-1">
        <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-5 sm:px-6">
          {turns.map((t, i) => (
            <TurnView
              key={t.id}
              task={t}
              last={i === turns.length - 1}
              onEnd={refresh}
              onRetry={() => act.mutate({ task: t, action: "retry" })}
              retrying={act.isPending}
            />
          ))}
          <div ref={endRef} />
        </div>
      </div>
      {failure && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {errorText(failure)}
        </p>
      )}
      <Composer
        onSend={(t) => send.mutateAsync(t)}
        onStop={
          answering && lastTurn ? () => act.mutate({ task: lastTurn, action: "cancel" }) : undefined
        }
        busy={send.isPending}
        model={current}
        models={ids}
        onModel={setModel}
        disabled={answering}
      />
    </>
  );
}

function Unavailable({ error }: { error: Error }) {
  const notConfigured =
    error instanceof ApiError &&
    (error.code === "provider_not_configured" || error.code === "database_not_configured");
  return (
    <Panel>
      <EmptyState
        icon={notConfigured ? Cpu : AlertTriangle}
        title={
          error instanceof ApiError && error.code === "provider_not_configured"
            ? "No model provider configured"
            : error instanceof ApiError && error.code === "database_not_configured"
              ? "Chat needs a database"
              : "Chat unavailable"
        }
      >
        {error.message}
      </EmptyState>
    </Panel>
  );
}

function ConversationList({ active }: { active: string | undefined }) {
  const list = useQuery({ queryKey: CONVERSATIONS, queryFn: chatApi.list, retry: false });
  return (
    <nav aria-label="Conversations" className="flex min-h-0 w-full flex-col gap-2">
      <Link
        to="/chat"
        className="flex h-8 items-center gap-2 rounded-control border border-border bg-surface-1 px-2.5 text-xs font-medium text-fg hover:bg-surface-2"
      >
        <Plus size={14} aria-hidden /> New chat
      </Link>
      {list.isError && <p className="px-1 text-xs text-danger">{list.error.message}</p>}
      {list.data?.length === 0 && (
        <p className="px-1 text-xs text-fg-subtle">Saved conversations appear here.</p>
      )}
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {list.data?.map((c) => (
          <li key={c.id}>
            <Link
              to={`/chat/${c.id}`}
              aria-current={c.id === active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-control px-2.5 py-1.5 text-xs text-fg-muted hover:bg-surface-2 hover:text-fg",
                c.id === active && "bg-surface-2 text-fg",
              )}
            >
              <span className="min-w-0 flex-1 truncate">{c.title}</span>
              {(c.last_state === "queued" || c.last_state === "running") && (
                <Spinner label="Answering" />
              )}
              {c.last_state === "waiting" && <Badge tone="warning">needs you</Badge>}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function ChatPage() {
  const { id } = useParams();
  const { models } = useModels();
  if (models.isError) return <Unavailable error={models.error} />;
  return (
    <div className="flex h-[calc(100dvh-3rem-3rem)] min-h-[420px] flex-col sm:h-[calc(100dvh-3rem-4rem)]">
      <div className="flex items-center gap-3 pb-4">
        {id && (
          <Link
            to="/chat"
            className="text-fg-muted hover:text-fg lg:hidden"
            aria-label="All conversations"
          >
            <ArrowLeft size={16} />
          </Link>
        )}
        <h1 className="text-[22px] leading-7 font-semibold tracking-[-0.015em]">Chat</h1>
        <Link
          to="/tasks"
          className="ml-auto flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg"
        >
          <ListChecks size={13} aria-hidden /> All tasks
        </Link>
      </div>
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div className={cn("min-h-0", id ? "hidden lg:flex" : "flex max-lg:max-h-48")}>
          <ConversationList active={id} />
        </div>
        <div className="flex min-h-0 min-w-0 flex-col">
          {id ? <ConversationView key={id} id={id} /> : <NewConversation />}
        </div>
      </div>
    </div>
  );
}
