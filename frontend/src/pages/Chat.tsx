import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Cpu,
  FolderKanban,
  ListChecks,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  Trash2,
  Wrench,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApprovalPrompt } from "../components/tasks/ApprovalPrompt";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ArtifactLinks } from "../components/studio/ArtifactLinks";
import { Markdown } from "../components/ui/Markdown";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { cn } from "../components/ui/cn";
import { ApiError, api } from "../lib/api";
import { chatApi } from "../lib/chat";
import type { Conversation, ConversationDetail, Turn } from "../lib/chat";
import { PROJECTS, projectKey, projectsApi } from "../lib/projects";
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
      {text && <Markdown text={text} toggle live />}
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

function Versions({
  turn,
  locked,
  onShow,
}: {
  turn: Turn;
  locked: boolean;
  onShow: (id: string) => void;
}) {
  const at = turn.versions.indexOf(turn.id);
  if (turn.versions.length < 2 || at < 0) return null;
  const prev = turn.versions[at - 1];
  const next = turn.versions[at + 1];
  return (
    <span className="flex items-center gap-0.5 text-xs text-fg-muted">
      <button
        type="button"
        aria-label="Previous version"
        disabled={locked || prev === undefined}
        onClick={() => prev && onShow(prev)}
        className="rounded p-0.5 hover:text-fg disabled:opacity-40"
      >
        <ChevronLeft size={14} aria-hidden />
      </button>
      <span className="tabular-nums" aria-label={`Version ${at + 1} of ${turn.versions.length}`}>
        {at + 1} / {turn.versions.length}
      </span>
      <button
        type="button"
        aria-label="Next version"
        disabled={locked || next === undefined}
        onClick={() => next && onShow(next)}
        className="rounded p-0.5 hover:text-fg disabled:opacity-40"
      >
        <ChevronRight size={14} aria-hidden />
      </button>
    </span>
  );
}

function TurnView({
  turn: task,
  conversationId,
  last,
  locked,
  onEnd,
  onRetry,
  onVersion,
  onShow,
}: {
  turn: Turn;
  conversationId: string;
  last: boolean;
  /** Something is being answered or changed: no new versions or switching. */
  locked: boolean;
  onEnd: () => void;
  onRetry: () => void;
  /** A new version of this message: edited with `prompt`, asked again without. */
  onVersion: (prompt?: string) => Promise<unknown>;
  onShow: (id: string) => void;
}) {
  const finished = isFinished(task.state);
  const tokens = task.usage.input_tokens + task.usage.output_tokens;
  const [draft, setDraft] = useState<string | null>(null);

  async function sendEdit(e: FormEvent) {
    e.preventDefault();
    if (draft === null || !draft.trim()) return;
    if (draft === task.prompt) return setDraft(null);
    try {
      await onVersion(draft);
      setDraft(null);
    } catch {
      // The conversation's error line says why; the draft stays for another try.
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {draft !== null ? (
        <form onSubmit={sendEdit} className="ml-auto flex w-full max-w-[80%] flex-col gap-2">
          <textarea
            aria-label="Edit message"
            value={draft}
            maxLength={20_000}
            rows={3}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setDraft(null);
            }}
            className="w-full resize-y rounded-panel border border-border bg-surface-1 px-3.5 py-2.5 text-sm text-fg outline-none focus:border-accent"
          />
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="mr-auto text-2xs text-fg-subtle">
              Sent as a new version; this one is kept.
            </span>
            <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button type="submit" size="sm" variant="primary" disabled={locked || !draft.trim()}>
              Send edit
            </Button>
          </div>
        </form>
      ) : (
        <div className="ml-auto flex max-w-[80%] flex-col items-end gap-1">
          <div className="rounded-panel bg-surface-3 px-3.5 py-2.5 text-sm whitespace-pre-wrap break-words text-fg">
            {task.prompt}
          </div>
          <div className="flex items-center gap-2">
            <Versions turn={task} locked={locked} onShow={onShow} />
            {finished && (
              <button
                type="button"
                onClick={() => setDraft(task.prompt)}
                disabled={locked}
                className="flex items-center gap-1 text-xs text-fg-muted hover:text-fg disabled:opacity-40"
              >
                <Pencil size={12} aria-hidden /> Edit
              </button>
            )}
          </div>
        </div>
      )}
      {!finished ? (
        <LiveReply task={task} onEnd={onEnd} />
      ) : (
        <div className="flex flex-col gap-2">
          <PastActivity task={task} />
          {task.state === "completed" && <Markdown text={task.result_text ?? ""} toggle />}
          <ArtifactLinks
            conversationId={conversationId}
            taskId={task.id}
            enabled={task.state === "completed"}
          />
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
                disabled={locked}
                className="flex items-center gap-1 font-sans text-xs text-fg-muted hover:text-fg"
              >
                <RotateCcw size={12} aria-hidden /> Try again
              </button>
            )}
            {task.state === "completed" && (
              <button
                type="button"
                onClick={() => void onVersion().catch(() => undefined)}
                disabled={locked}
                className="flex items-center gap-1 font-sans text-xs text-fg-muted hover:text-fg disabled:opacity-40"
              >
                <RefreshCw size={12} aria-hidden /> Regenerate
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
  const [params] = useSearchParams();
  const projectId = params.get("project") ?? undefined;
  const project = useQuery({
    queryKey: projectKey(projectId ?? ""),
    queryFn: () => projectsApi.get(projectId ?? ""),
    enabled: projectId !== undefined,
    retry: false,
  });
  const start = useMutation({
    mutationFn: (prompt: string) =>
      chatApi.start(
        { model: model || fallback, prompt, ...(projectId && { project_id: projectId }) },
        crypto.randomUUID(),
      ),
    onSuccess: (detail) => {
      qc.setQueryData(conversationKey(detail.conversation.id), detail);
      void qc.invalidateQueries({ queryKey: CONVERSATIONS });
      if (projectId) void qc.invalidateQueries({ queryKey: PROJECTS });
      navigate(`/chat/${detail.conversation.id}`);
    },
  });
  return (
    <>
      {projectId && (
        <p className="flex items-center gap-1.5 pb-3 text-xs text-fg-muted">
          <FolderKanban size={13} aria-hidden />
          {project.isError ? (
            <span role="alert" className="text-danger">
              {errorText(project.error)}
            </span>
          ) : (
            <>
              New chat in{" "}
              <Link to={`/projects/${projectId}`} className="text-accent hover:underline">
                {project.data?.name ?? "…"}
              </Link>
              <Link to="/chat" className="ml-auto hover:text-fg">
                Start outside it
              </Link>
            </>
          )}
        </p>
      )}
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

function ConversationHeader({
  conversation,
  turns,
  answering,
}: {
  conversation: Conversation;
  turns: number;
  answering: boolean;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"view" | "rename" | "delete">("view");
  const [title, setTitle] = useState(conversation.title);
  const rename = useMutation({
    mutationFn: (t: string) => chatApi.rename(conversation.id, t),
    onSuccess: (conv) => {
      qc.setQueryData<ConversationDetail>(conversationKey(conv.id), (d) =>
        d ? { ...d, conversation: conv } : d,
      );
      void qc.invalidateQueries({ queryKey: conversationKey(conv.id) });
      void qc.invalidateQueries({ queryKey: CONVERSATIONS });
      setMode("view");
    },
  });
  const remove = useMutation({
    mutationFn: () => chatApi.remove(conversation.id),
    onSuccess: () => {
      qc.removeQueries({ queryKey: conversationKey(conversation.id) });
      void qc.invalidateQueries({ queryKey: CONVERSATIONS });
      navigate("/chat");
    },
  });
  const projects = useQuery({ queryKey: PROJECTS, queryFn: projectsApi.list, retry: false });
  const move = useMutation({
    mutationFn: (projectId: string | null) => chatApi.move(conversation.id, projectId),
    onSuccess: (conv) => {
      qc.setQueryData<ConversationDetail>(conversationKey(conv.id), (d) =>
        d ? { ...d, conversation: conv } : d,
      );
      void qc.invalidateQueries({ queryKey: CONVERSATIONS });
      void qc.invalidateQueries({ queryKey: PROJECTS });
    },
  });
  const failure = rename.error ?? remove.error ?? move.error;

  function save(e: FormEvent) {
    e.preventDefault();
    const next = title.split(/\s+/).filter(Boolean).join(" ");
    if (!next) return;
    if (next === conversation.title) setMode("view");
    else rename.mutate(next);
  }

  return (
    <div className="pb-3">
      {mode === "rename" ? (
        <form onSubmit={save} className="flex items-center gap-2">
          <input
            aria-label="Conversation title"
            value={title}
            maxLength={80}
            autoFocus
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setMode("view");
            }}
            className="h-8 min-w-0 flex-1 rounded-control border border-border bg-surface-1 px-2.5 text-sm text-fg outline-none focus:border-accent"
          />
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={rename.isPending || !title.trim()}
          >
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setMode("view")}>
            Cancel
          </Button>
        </form>
      ) : (
        <div className="flex items-center gap-1">
          <h2 className="min-w-0 flex-1 truncate text-sm font-medium text-fg">
            {conversation.title}
          </h2>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Rename conversation"
            onClick={() => {
              setTitle(conversation.title);
              rename.reset();
              setMode("rename");
            }}
          >
            <Pencil size={14} aria-hidden />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Delete conversation"
            title={answering ? "Stop the answer before deleting" : undefined}
            disabled={answering}
            onClick={() => {
              remove.reset();
              setMode("delete");
            }}
          >
            <Trash2 size={14} aria-hidden />
          </Button>
        </div>
      )}
      {projects.data && (projects.data.length > 0 || conversation.project_id) && (
        <div className="mt-1 flex items-center gap-1.5 text-xs text-fg-muted">
          <FolderKanban size={13} aria-hidden />
          <label htmlFor="conversation-project">Project</label>
          <select
            id="conversation-project"
            value={conversation.project_id ?? ""}
            disabled={move.isPending}
            onChange={(e) => move.mutate(e.target.value || null)}
            className="h-7 max-w-48 min-w-0 truncate rounded-control border border-border bg-surface-1 px-1.5 text-xs text-fg outline-none focus:border-accent"
          >
            <option value="">None</option>
            {projects.data.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {conversation.project_id && (
            <Link to={`/projects/${conversation.project_id}`} className="hover:text-fg">
              Open project
            </Link>
          )}
          {(projects.data.find((p) => p.id === conversation.project_id)?.proposed_memories ?? 0) >
            0 && (
            <Link
              to={`/projects/${conversation.project_id}`}
              className="text-accent hover:underline"
            >
              Memory to review
            </Link>
          )}
        </div>
      )}
      {mode === "delete" && (
        <div
          role="alertdialog"
          aria-label="Delete conversation"
          className="mt-2 flex flex-wrap items-center gap-2 rounded-control border border-danger bg-danger-soft px-3 py-2 text-xs text-fg"
        >
          <p className="min-w-0 flex-1">
            Delete this conversation and its {turns === 1 ? "1 message" : `${turns} messages`}?
            Their timelines go too. This cannot be undone.
          </p>
          <Button
            size="sm"
            className="border-danger text-danger"
            disabled={remove.isPending || answering}
            onClick={() => remove.mutate()}
          >
            Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setMode("view")}>
            Keep
          </Button>
        </div>
      )}
      {failure && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {errorText(failure)}
        </p>
      )}
    </div>
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
    void qc.invalidateQueries({ queryKey: PROJECTS }); // the answer may have proposed memory
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
        d ? { ...d, turns: [...d.turns, { ...task, versions: [task.id] }] } : d,
      );
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: ({ task, action }: { task: Task; action: "cancel" | "retry" }) =>
      action === "cancel" ? tasksApi.cancel(task.id) : tasksApi.retry(task.id),
    onSettled: refresh,
  });
  const version = useMutation({
    mutationFn: ({ turn, prompt }: { turn: Turn; prompt?: string }) =>
      chatApi.addVersion(
        id,
        turn.id,
        {
          ...(prompt !== undefined && { prompt }),
          ...(current !== detail.data?.conversation.model && { model: current }),
        },
        crypto.randomUUID(),
      ),
    // Stays pending until the conversation is refetched with the new version as
    // the shown path's end, so nothing else can be sent in between.
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: conversationKey(id) }),
        qc.invalidateQueries({ queryKey: CONVERSATIONS }),
      ]),
  });
  const show = useMutation({
    mutationFn: (turnId: string) => chatApi.show(id, turnId),
    onSuccess: (d) => {
      qc.setQueryData(conversationKey(id), d);
      void qc.invalidateQueries({ queryKey: CONVERSATIONS });
    },
  });
  const locked = answering || act.isPending || version.isPending || show.isPending;

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

  const failure = send.error ?? act.error ?? version.error ?? show.error;
  return (
    <>
      <ConversationHeader
        conversation={detail.data.conversation}
        turns={turns.length}
        answering={answering}
      />
      <div className="min-h-0 flex-1 overflow-y-auto rounded-panel border border-border bg-surface-1">
        <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-5 sm:px-6">
          {turns.map((t, i) => (
            <TurnView
              key={t.id}
              turn={t}
              conversationId={id}
              last={i === turns.length - 1}
              locked={locked}
              onEnd={refresh}
              onRetry={() => act.mutate({ task: t, action: "retry" })}
              onVersion={(prompt) => version.mutateAsync({ turn: t, prompt })}
              onShow={(turnId) => show.mutate(turnId)}
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
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  // Search after a pause in typing, not on every key.
  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);
  const list = useQuery({
    queryKey: [...CONVERSATIONS, query],
    queryFn: () => chatApi.list(query),
    retry: false,
    placeholderData: keepPreviousData,
  });
  return (
    <nav aria-label="Conversations" className="flex min-h-0 w-full flex-col gap-2">
      <Link
        to="/chat"
        className="flex h-8 items-center gap-2 rounded-control border border-border bg-surface-1 px-2.5 text-xs font-medium text-fg hover:bg-surface-2"
      >
        <Plus size={14} aria-hidden /> New chat
      </Link>
      <label className="relative block">
        <span className="sr-only">Search conversations</span>
        <Search
          size={13}
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-fg-subtle"
        />
        <input
          type="search"
          value={search}
          maxLength={200}
          placeholder="Search"
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 w-full rounded-control border border-border bg-surface-1 pr-2.5 pl-7 text-xs text-fg outline-none placeholder:text-fg-subtle focus:border-accent"
        />
      </label>
      {list.isError && <p className="px-1 text-xs text-danger">{list.error.message}</p>}
      {list.data?.length === 0 && (
        <p className="px-1 text-xs text-fg-subtle">
          {query ? `No conversations match “${query}”.` : "Saved conversations appear here."}
        </p>
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
