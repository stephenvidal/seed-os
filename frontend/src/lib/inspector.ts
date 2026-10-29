/**
 * Folds a task's event log into the Execution Inspector's tables: attempts, model
 * steps, tool calls and checkpoints. Only recorded facts: model reasoning is
 * never stored, so it is never shown.
 */
import type { TaskEvent } from "./tasks";

/** One run of the task by a worker. A pause for approval or a shutdown hands the
 * attempt back uncounted, so the run that resumes it repeats the number. */
export type AttemptRow = {
  attempt: number;
  startedAt: string;
  worker: string | null;
  /** The step a checkpoint let this attempt skip to, if any. */
  resumedAtStep: number | null;
  endedAt: string | null;
  /** How the attempt ended: a run termination, or what the queue did to it. */
  outcome: string | null;
};

export type StepRow = {
  attempt: number;
  step: number;
  startedAt: string;
  wrapUp: boolean;
  /** Provider retries while this step waited for an answer. */
  retries: number;
  latencyMs: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  finishReason: string | null;
  toolCalls: number;
};

export type ToolRow = {
  attempt: number;
  step: number;
  id: string;
  name: string;
  args: unknown;
  ok: boolean | null;
  errorKind: string | null;
  error: string | null;
  durationMs: number | null;
  decision: "approved" | "denied" | null;
};

export type CheckpointRow = {
  seq: number;
  at: string;
  attempt: number;
  steps: number;
  pending: number;
};

export type Inspection = {
  attempts: AttemptRow[];
  steps: StepRow[];
  tools: ToolRow[];
  checkpoints: CheckpointRow[];
  totals: {
    inputTokens: number;
    outputTokens: number;
    modelMs: number;
    toolMs: number;
    retries: number;
  };
  /** Streamed text chunks, counted rather than listed. */
  textDeltas: number;
};

const num = (v: unknown) => (typeof v === "number" ? v : null);

export function inspect(events: TaskEvent[]): Inspection {
  const attempts: AttemptRow[] = [];
  const steps: StepRow[] = [];
  const tools: ToolRow[] = [];
  const checkpoints: CheckpointRow[] = [];
  let textDeltas = 0;
  let retries = 0;

  // Providers may reuse call ids from step to step ("call_0"), so a result or a
  // decision belongs to the newest call with its id.
  const latest = (id: string) => [...tools].reverse().find((t) => t.id === id);
  const end = (e: TaskEvent, outcome: string) => {
    const a = attempts.at(-1);
    if (a && a.attempt === e.attempt && a.outcome === null) {
      a.outcome = outcome;
      a.endedAt = e.created_at;
    }
  };

  for (const e of events) {
    const d = e.data;
    switch (e.type) {
      case "attempt_started":
        attempts.push({
          attempt: e.attempt,
          startedAt: e.created_at,
          worker: typeof d.worker === "string" ? d.worker : null,
          resumedAtStep: num(d.resumed_at_step),
          endedAt: null,
          outcome: null,
        });
        break;
      case "provider_retry": {
        // Retries happen inside the step that is waiting on the provider.
        const s = steps.at(-1);
        if (s && s.attempt === e.attempt) s.retries += 1;
        retries += 1;
        break;
      }
      case "step_started":
        steps.push({
          attempt: e.attempt,
          step: Number(d.step),
          startedAt: e.created_at,
          wrapUp: d.wrap_up === true,
          retries: 0,
          latencyMs: null,
          inputTokens: null,
          outputTokens: null,
          finishReason: null,
          toolCalls: 0,
        });
        break;
      case "step_completed": {
        const s = [...steps]
          .reverse()
          .find((x) => x.attempt === e.attempt && x.step === Number(d.step));
        const u = d.usage as { input_tokens?: number; output_tokens?: number } | undefined;
        if (s) {
          s.latencyMs = num(d.latency_ms);
          s.inputTokens = num(u?.input_tokens);
          s.outputTokens = num(u?.output_tokens);
          s.finishReason = typeof d.finish_reason === "string" ? d.finish_reason : null;
          s.toolCalls = num(d.tool_calls) ?? 0;
        }
        break;
      }
      case "text_delta":
        textDeltas += 1;
        break;
      case "tool_call":
        tools.push({
          attempt: e.attempt,
          step: Number(d.step),
          id: String(d.id),
          name: String(d.name),
          args: d.arguments,
          ok: null,
          errorKind: null,
          error: null,
          durationMs: null,
          decision: null,
        });
        break;
      case "tool_result": {
        const t = latest(String(d.id));
        if (t) {
          t.ok = Boolean(d.ok);
          t.errorKind = typeof d.error_kind === "string" ? d.error_kind : null;
          t.error = typeof d.error === "string" ? d.error : null;
          t.durationMs = num(d.duration_ms);
        }
        break;
      }
      case "approval_decided": {
        const t = latest(String(d.id));
        if (t) t.decision = d.approved ? "approved" : "denied";
        break;
      }
      case "checkpoint_saved":
        checkpoints.push({
          seq: e.seq,
          at: e.created_at,
          attempt: e.attempt,
          steps: Number(d.steps),
          pending: num(d.pending) ?? 0,
        });
        break;
      case "run_finished":
        end(e, String(d.termination));
        break;
      case "lease_expired":
        end(e, "worker stopped responding");
        break;
      case "task_released":
        end(e, "handed back at worker shutdown");
        break;
      default:
        break;
    }
  }

  const sum = (xs: (number | null)[]) => xs.reduce<number>((a, b) => a + (b ?? 0), 0);
  return {
    attempts,
    steps,
    tools,
    checkpoints,
    totals: {
      inputTokens: sum(steps.map((s) => s.inputTokens)),
      outputTokens: sum(steps.map((s) => s.outputTokens)),
      modelMs: sum(steps.map((s) => s.latencyMs)),
      toolMs: sum(tools.map((t) => t.durationMs)),
      retries,
    },
    textDeltas,
  };
}
