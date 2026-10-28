/** Client for the durable Tasks API (/api/v1/tasks) and its live event stream. */
import { request } from "./api";

export type TaskState = "queued" | "running" | "completed" | "failed" | "canceled";

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
  /** The key makes a double-submitted form create one task, not two. */
  create: (body: { model: string; prompt: string }, idempotencyKey: string) =>
    request<Task>("/api/v1/tasks", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  cancel: (id: string) => request<Task>(`/api/v1/tasks/${id}/cancel`, { method: "POST" }),
  retry: (id: string) => request<Task>(`/api/v1/tasks/${id}/retry`, { method: "POST" }),
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
  cancelled: "Canceled",
  max_steps: "Stopped: step limit reached",
  deadline: "Stopped: time limit reached",
  token_budget: "Stopped: token budget reached",
  provider_error: "Stopped: model provider error",
};

/** Folds the event log into a readable timeline: lifecycle notes and model steps. */
export function toTimeline(events: TaskEvent[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  const note = (e: TaskEvent, tone: "neutral" | "accent" | "warning" | "danger", text: string) =>
    items.push({ kind: "note", seq: e.seq, at: e.created_at, tone, text });
  const current = () => {
    const last = items.at(-1);
    return last?.kind === "step" ? last : undefined;
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
        current()?.tools.push({ id: String(d.id), name: String(d.name), args: d.arguments });
        break;
      case "tool_result": {
        const t = current()?.tools.find((x) => x.id === String(d.id) && x.ok === undefined);
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
      case "run_finished": {
        const term = String(d.termination);
        const text = TERMINATION_TEXT[term] ?? `Stopped: ${term}`;
        note(
          e,
          term === "completed" ? "accent" : term === "cancelled" ? "neutral" : "danger",
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
