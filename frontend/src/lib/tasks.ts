/** Client for the durable Tasks API (/api/v1/tasks) and its live event stream. */
import { request } from "./api";

export type TaskState = "queued" | "running" | "waiting" | "completed" | "failed" | "canceled";

/** A tool call as the model made it. */
export type ToolCallInfo = { id: string; name: string; arguments: Record<string, unknown> };

export type Task = {
  id: string;
  title: string;
  model: string;
  prompt: string;
  state: TaskState;
  attempt: number;
  max_attempts: number;
  cancel_requested: boolean;
  termination: string | null;
  error: string | null;
  result_text: string | null;
  usage: { input_tokens: number; output_tokens: number };
  last_seq: number;
  resumable_from_step: number | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Set when the task is a chat turn. */
  conversation_id: string | null;
  turn: number | null;
  /** The project the task ran in, if any. */
  project_id: string | null;
  /** The newest earlier turn the model saw only in summary (chat turns). */
  summary_of: string | null;
  /** The summary of the chat through this turn, once a later turn needed it. */
  summary: string | null;
  /** Set while the task is waiting: the call that needs a person's decision. */
  awaiting_approval: ToolCallInfo | null;
  /** Set while the task waits for a task it delegated to an agent. */
  awaiting_delegation?: ToolCallInfo | null;
  /** On a delegated task: the task that delegated it. */
  parent_task_id?: string | null;
  /** On a delegated task: the agent it runs as, as it was when delegated. */
  agent?: { id: string; name: string; description: string } | null;
  /** The owner's check, run once the agent says it is done (D-038). */
  check_command?: string | null;
  /** What running the check came to; its exit code decides. */
  verification?: Verification | null;
};

export type Verification = {
  command: string;
  passed: boolean;
  /** Null when the command was killed or could not be run. */
  exit_code: number | null;
  timed_out: boolean;
  stdout: string;
  stderr: string;
  duration_ms: number;
};

export type TaskEvent = {
  seq: number;
  attempt: number;
  type: string;
  data: Record<string, unknown>;
  created_at: string;
};

export const isFinished = (s: TaskState) => s === "completed" || s === "failed" || s === "canceled";

export const tasksApi = {
  list: () => request<Task[]>("/api/v1/tasks?limit=100"),
  get: (id: string) => request<Task>(`/api/v1/tasks/${id}`),
  /** A project's tasks started outside a chat, newest first. */
  inProject: (projectId: string) =>
    request<Task[]>(`/api/v1/tasks?limit=100&project_id=${encodeURIComponent(projectId)}`),
  /** The key makes a double-submitted form create one task, not two. */
  create: (
    body: { model: string; prompt: string; project_id?: string; check?: string },
    idempotencyKey: string,
  ) =>
    request<Task>("/api/v1/tasks", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  cancel: (id: string) => request<Task>(`/api/v1/tasks/${id}/cancel`, { method: "POST" }),
  retry: (id: string) => request<Task>(`/api/v1/tasks/${id}/retry`, { method: "POST" }),
  decide: (id: string, callId: string, approve: boolean) =>
    request<Task>(`/api/v1/tasks/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ call_id: callId, approve }),
    }),
  events: (id: string, after = 0) =>
    request<{ events: TaskEvent[]; last_seq: number; state: TaskState }>(
      `/api/v1/tasks/${id}/events?after=${after}&limit=1000`,
    ),
  /** Every event so far, page by page (a long answer has many text deltas). */
  allEvents: async (id: string) => {
    const all: TaskEvent[] = [];
    for (;;) {
      const page = await tasksApi.events(id, all.at(-1)?.seq ?? 0);
      all.push(...page.events);
      if (page.events.length === 0 || (all.at(-1)?.seq ?? 0) >= page.last_seq) return all;
    }
  },
};

/**
 * Follows a task's events. EventSource reconnects on its own and sends
 * Last-Event-ID, so the server resumes after the last event received: no gaps,
 * no duplicates. Returns a function that closes the stream.
 */
export function followTask(
  id: string,
  after: number,
  onEvent: (e: TaskEvent) => void,
  onEnd: () => void,
): () => void {
  const source = new EventSource(`/api/v1/tasks/${id}/stream?after=${after}`);
  source.onmessage = (m: MessageEvent<string>) => onEvent(JSON.parse(m.data) as TaskEvent);
  source.addEventListener("end", () => {
    source.close();
    onEnd();
  });
  return () => source.close();
}

export type ToolActivity = {
  id: string;
  name: string;
  args: unknown;
  ok?: boolean;
  error?: string;
  durationMs?: number;
};

export type TimelineItem =
  | {
      kind: "note";
      seq: number;
      at: string;
      tone: "neutral" | "accent" | "warning" | "danger";
      text: string;
    }
  | {
      kind: "step";
      seq: number;
      attempt: number;
      step: number;
      text: string;
      tools: ToolActivity[];
      tokens?: { input: number; output: number };
      done: boolean;
    };

const TERMINATION_TEXT: Record<string, string> = {
  completed: "Finished",
  awaiting_approval: "Paused for your approval",
  awaiting_delegation: "Waiting for an agent",
  cancelled: "Canceled",
  max_steps: "Stopped: step limit reached",
  deadline: "Stopped: time limit reached",
  token_budget: "Stopped: token budget reached",
  check_failed: "Failed its check",
  check_unavailable: "Not run: its check needs the sandbox",
  cost_budget: "Stopped: spend limit for this task reached",
  daily_budget: "Not run: daily spend limit used up",
  price_unknown: "Not run: model price unknown, spend limit cannot be checked",
  provider_error: "Stopped: model provider error",
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Folds the event log into a readable timeline: lifecycle notes and model steps. */
export function toTimeline(events: TaskEvent[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  const note = (e: TaskEvent, tone: "neutral" | "accent" | "warning" | "danger", text: string) =>
    items.push({ kind: "note", seq: e.seq, at: e.created_at, tone, text });
  const current = () => {
    const last = items.at(-1);
    return last?.kind === "step" ? last : undefined;
  };
  // A step's calls can finish after a pause for approval, with notes in between.
  const lastStep = () => {
    for (let i = items.length - 1; i >= 0; i--) {
      const item = items[i]!;
      if (item.kind === "step") return item;
    }
    return undefined;
  };

  for (const e of events) {
    const d = e.data;
    switch (e.type) {
      case "task_created":
        note(e, "neutral", "Created");
        break;
      case "attempt_started":
        note(
          e,
          "neutral",
          typeof d.resumed_at_step === "number"
            ? `Attempt ${e.attempt} resumed after step ${d.resumed_at_step}`
            : `Attempt ${e.attempt} started`,
        );
        break;
      case "step_started":
        items.push({
          kind: "step",
          seq: e.seq,
          attempt: e.attempt,
          step: Number(d.step),
          text: "",
          tools: [],
          done: false,
        });
        break;
      case "text_delta": {
        const s = current();
        if (s) s.text += String(d.text ?? "");
        break;
      }
      case "tool_call":
        lastStep()?.tools.push({ id: String(d.id), name: String(d.name), args: d.arguments });
        break;
      case "tool_result": {
        const t = lastStep()?.tools.find((x) => x.id === String(d.id) && x.ok === undefined);
        if (t) {
          t.ok = Boolean(d.ok);
          t.error = d.ok ? undefined : String(d.error ?? d.error_kind ?? "failed");
          t.durationMs = typeof d.duration_ms === "number" ? d.duration_ms : undefined;
        }
        break;
      }
      case "step_completed": {
        const s = current();
        const u = d.usage as { input_tokens: number; output_tokens: number } | undefined;
        if (s) {
          s.done = true;
          if (u) s.tokens = { input: u.input_tokens, output: u.output_tokens };
        }
        break;
      }
      case "provider_retry":
        note(e, "warning", `Model provider ${String(d.kind)}; retrying in ${String(d.delay_s)} s`);
        break;
      case "approval_requested":
        note(e, "warning", `Waiting for your approval to run ${String(d.name)}`);
        break;
      case "approval_decided":
        note(
          e,
          d.approved ? "accent" : "neutral",
          `${d.approved ? "Approved" : "Denied"} by ${String(d.by)}`,
        );
        break;
      case "run_finished": {
        const term = String(d.termination);
        const text = TERMINATION_TEXT[term] ?? `Stopped: ${term}`;
        note(
          e,
          term === "completed"
            ? "accent"
            : term === "cancelled"
              ? "neutral"
              : term === "awaiting_approval"
                ? "warning"
                : "danger",
          d.error ? `${text} (${String(d.error)})` : text,
        );
        break;
      }
      case "cancel_requested":
        note(
          e,
          "neutral",
          d.state === "canceled" ? "Canceled before it started" : "Cancel requested",
        );
        break;
      case "task_requeued":
        note(e, "neutral", "Queued again for retry");
        break;
      case "task_released":
        note(e, "warning", "Worker shut down; task handed back to the queue");
        break;
      case "artifacts_saved": {
        const saved = (d.saved ?? []) as { path: string; version: number; deleted: boolean }[];
        const skipped = (d.skipped ?? []) as { path: string; reason: string }[];
        const named = saved
          .slice(0, 5)
          .map((s) => (s.deleted ? `${s.path} (deleted)` : `${s.path} v${s.version}`));
        const more = saved.length > 5 ? `, and ${saved.length - 5} more` : "";
        if (saved.length)
          note(e, "accent", `Saved ${plural(saved.length, "file")}: ${named.join(", ")}${more}`);
        if (skipped.length)
          note(
            e,
            "warning",
            `Not saved: ${skipped.map((s) => `${s.path} (${s.reason.replace("_", " ")})`).join(", ")}`,
          );
        if (d.truncated) note(e, "warning", "Too many files to save them all");
        break;
      }
      case "workspace_restored":
        note(
          e,
          "neutral",
          `Workspace was empty; put back ${plural(Number(d.files), "saved file")}`,
        );
        break;
      case "artifacts_failed":
        note(
          e,
          "danger",
          `${d.stage === "restore" ? "Restoring" : "Saving"} files failed: ${String(d.error)}`,
        );
        break;
      case "context_summarized":
        note(
          e,
          "neutral",
          Number(d.turns)
            ? `Summarized ${plural(Number(d.turns), "earlier turn")} for the model`
            : "Gave the model the saved summary of earlier turns",
        );
        break;
      case "summary_failed":
        note(e, "warning", `Could not summarize earlier turns: ${String(d.error)}`);
        break;
      case "delegated":
        note(e, "neutral", `Handed to ${String(d.agent)} as a task of its own`);
        break;
      case "delegation_refused":
        note(e, "warning", `Not delegated: ${String(d.reason)}`);
        break;
      case "delegation_finished":
        note(
          e,
          d.state === "completed" ? "accent" : "warning",
          `${String(d.agent)} ${d.state === "completed" ? "reported back" : `stopped: ${String(d.state)}`}`,
        );
        break;
      case "verification":
        note(
          e,
          d.passed ? "accent" : "danger",
          d.passed
            ? "Check passed (exit code 0)"
            : d.timed_out
              ? "Check failed: it ran out of time"
              : d.exit_code === null
                ? "Check failed: it could not be run"
                : `Check failed (exit code ${String(d.exit_code)})`,
        );
        break;
      case "mcp_unavailable":
        note(
          e,
          "warning",
          `MCP server ${String(d.server)} did not connect (${String(d.reason)}); its tools were left out`,
        );
        break;
      case "lease_expired":
        note(
          e,
          "danger",
          d.state === "canceled"
            ? "Worker stopped responding; task canceled"
            : "Worker stopped responding on every attempt; task failed",
        );
        break;
      default:
        break;
    }
  }
  return items;
}

/**
 * The call a task is waiting on, read from its events: the last approval request
 * with no decision after it, unless the task was canceled since.
 */
export function pendingApproval(events: TaskEvent[]): ToolCallInfo | null {
  let pending: ToolCallInfo | null = null;
  for (const e of events) {
    const d = e.data;
    if (e.type === "approval_requested")
      pending = {
        id: String(d.id),
        name: String(d.name),
        arguments: (d.arguments ?? {}) as Record<string, unknown>,
      };
    else if (e.type === "approval_decided" || e.type === "cancel_requested") pending = null;
  }
  return pending;
}

/**
 * The agent tasks a task has working for it, read from its events: each delegation
 * that has not reported back, until the task is canceled or its run ends other than
 * by waiting for them. One step can hand work to several agents at once (D-026).
 */
export function pendingDelegations(
  events: TaskEvent[],
): { id: string; agent: string; taskId: string }[] {
  let open: { id: string; agent: string; taskId: string }[] = [];
  for (const e of events) {
    const d = e.data;
    if (e.type === "delegated")
      open.push({ id: String(d.id), agent: String(d.agent), taskId: String(d.task_id) });
    else if (e.type === "delegation_finished") open = open.filter((o) => o.id !== String(d.id));
    else if (
      e.type === "cancel_requested" ||
      (e.type === "run_finished" && d.termination !== "awaiting_delegation")
    )
      open = [];
  }
  return open;
}

export type DelegatedTask = {
  id: string;
  agent: string;
  taskId: string;
  /** The agent task's end state, once it has reported back; unset while it works. */
  state?: TaskState;
};

/**
 * Every agent task a task handed work to, read from its events, in the order they
 * started. Unlike pendingDelegations this lasts after the task ends (D-026).
 */
export function delegatedTasks(events: TaskEvent[]): DelegatedTask[] {
  const all: DelegatedTask[] = [];
  for (const e of events) {
    const d = e.data;
    if (e.type === "delegated")
      all.push({ id: String(d.id), agent: String(d.agent), taskId: String(d.task_id) });
    else if (e.type === "delegation_finished")
      for (const a of all) if (a.id === String(d.id)) a.state = d.state as TaskState;
  }
  return all;
}
