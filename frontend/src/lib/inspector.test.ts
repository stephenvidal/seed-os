import { describe, expect, it } from "vitest";
import { inspect } from "./inspector";
import type { TaskEvent } from "./tasks";

let seq = 0;
const ev = (attempt: number, type: string, data: Record<string, unknown> = {}): TaskEvent => ({
  seq: ++seq,
  attempt,
  type,
  data,
  created_at: `2026-10-29T12:00:${String(seq).padStart(2, "0")}Z`,
});

/** Attempt 1 dies after a checkpoint; attempt 2 resumes, waits for approval, finishes.
 * Ollama numbers calls per step, so both steps call "call_0". */
const LOG: TaskEvent[] = [
  ev(0, "task_created"),
  ev(1, "attempt_started", { attempt: 1, worker: "w-1", resumed_at_step: null }),
  ev(1, "step_started", { step: 1 }),
  ev(1, "provider_retry", { attempt: 1, kind: "rate_limited", delay_s: 1 }),
  ev(1, "text_delta", { text: "Look" }),
  ev(1, "text_delta", { text: "ing" }),
  ev(1, "step_completed", {
    step: 1,
    finish_reason: "tool_calls",
    usage: { input_tokens: 100, output_tokens: 20 },
    latency_ms: 1500,
    tool_calls: 1,
  }),
  ev(1, "tool_call", { step: 1, id: "call_0", name: "read_file", arguments: { path: "a" } }),
  ev(1, "tool_result", { step: 1, id: "call_0", ok: true, duration_ms: 12 }),
  ev(1, "checkpoint_saved", { steps: 1, pending: 0 }),
  ev(1, "lease_expired", { state: "queued" }),
  ev(2, "attempt_started", { attempt: 2, worker: "w-2", resumed_at_step: 1 }),
  ev(2, "step_started", { step: 2 }),
  ev(2, "step_completed", {
    step: 2,
    finish_reason: "tool_calls",
    usage: { input_tokens: 150, output_tokens: 30 },
    latency_ms: 800,
    tool_calls: 1,
  }),
  ev(2, "tool_call", { step: 2, id: "call_0", name: "run_command", arguments: { command: "ls" } }),
  ev(2, "approval_requested", { id: "call_0", name: "run_command" }),
  ev(2, "checkpoint_saved", { steps: 1, pending: 1 }),
  ev(2, "run_finished", { termination: "awaiting_approval" }),
  ev(2, "approval_decided", { id: "call_0", approved: true, by: "admin" }),
  // The pause handed the attempt back, so the resumed run is attempt 2 again.
  ev(2, "attempt_started", { attempt: 2, worker: "w-1", resumed_at_step: 2 }),
  // On resume the call is not announced again; its result arrives.
  ev(2, "tool_result", {
    step: 2,
    id: "call_0",
    ok: false,
    error_kind: "exit",
    error: "exit 1",
    duration_ms: 40,
  }),
  ev(2, "step_started", { step: 3, wrap_up: true }),
  ev(2, "step_completed", {
    step: 3,
    finish_reason: "stop",
    usage: { input_tokens: 200, output_tokens: 10 },
    latency_ms: 300,
    tool_calls: 0,
  }),
  ev(2, "run_finished", { termination: "completed" }),
];

describe("inspect", () => {
  const x = inspect(LOG);

  it("splits the run into attempts with how each one ended", () => {
    expect(x.attempts).toEqual([
      {
        attempt: 1,
        startedAt: LOG[1]!.created_at,
        worker: "w-1",
        resumedAtStep: null,
        endedAt: LOG[10]!.created_at,
        outcome: "worker stopped responding",
      },
      {
        attempt: 2,
        startedAt: LOG[11]!.created_at,
        worker: "w-2",
        resumedAtStep: 1,
        endedAt: LOG[17]!.created_at,
        outcome: "awaiting_approval",
      },
      {
        attempt: 2,
        startedAt: LOG[19]!.created_at,
        worker: "w-1",
        resumedAtStep: 2,
        endedAt: LOG[23]!.created_at,
        outcome: "completed",
      },
    ]);
  });

  it("lists model steps with retries, latency and tokens", () => {
    expect(
      x.steps.map((s) => [
        s.attempt,
        s.step,
        s.retries,
        s.latencyMs,
        s.inputTokens,
        s.outputTokens,
        s.finishReason,
        s.toolCalls,
        s.wrapUp,
      ]),
    ).toEqual([
      [1, 1, 1, 1500, 100, 20, "tool_calls", 1, false],
      [2, 2, 0, 800, 150, 30, "tool_calls", 1, false],
      [2, 3, 0, 300, 200, 10, "stop", 0, true],
    ]);
  });

  it("lists each tool call once, with its result and decision", () => {
    expect(x.tools).toEqual([
      {
        attempt: 1,
        step: 1,
        id: "call_0",
        name: "read_file",
        args: { path: "a" },
        ok: true,
        errorKind: null,
        error: null,
        durationMs: 12,
        decision: null,
      },
      {
        attempt: 2,
        step: 2,
        id: "call_0",
        name: "run_command",
        args: { command: "ls" },
        ok: false,
        errorKind: "exit",
        error: "exit 1",
        durationMs: 40,
        decision: "approved",
      },
    ]);
  });

  it("records checkpoints and totals, and counts text chunks", () => {
    expect(x.checkpoints).toEqual([
      { seq: 10, at: LOG[9]!.created_at, attempt: 1, steps: 1, pending: 0 },
      { seq: 17, at: LOG[16]!.created_at, attempt: 2, steps: 1, pending: 1 },
    ]);
    expect(x.totals).toEqual({
      inputTokens: 450,
      outputTokens: 60,
      modelMs: 2600,
      toolMs: 52,
      retries: 1,
    });
    expect(x.textDeltas).toBe(2);
  });

  it("returns empty tables for a task that has not started", () => {
    const y = inspect([ev(0, "task_created")]);
    expect([y.attempts, y.steps, y.tools, y.checkpoints]).toEqual([[], [], [], []]);
    expect(y.totals.inputTokens).toBe(0);
  });

  it("lists hand-offs to agents, how each ended, and the ones refused", () => {
    const log: TaskEvent[] = [
      ev(1, "delegated", { id: "c1", agent: "Researcher", task_id: "t9" }),
      ev(1, "delegated", { id: "c2", agent: "Coder", task_id: "t8" }),
      ev(1, "delegation_refused", { id: "c3", reason: "No agent named 'X'." }),
      ev(1, "delegation_finished", { id: "c2", agent: "Coder", state: "failed" }),
    ];
    const rows = inspect(log).delegations;
    expect(rows.map((r) => [r.id, r.agent, r.taskId, r.state, r.refused])).toEqual([
      ["c1", "Researcher", "t9", null, null],
      ["c2", "Coder", "t8", "failed", null],
      ["c3", null, null, null, "No agent named 'X'."],
    ]);
    expect(rows[0]!.endedAt).toBeNull(); // still working
    expect(rows[1]!.endedAt).not.toBeNull();
    expect(rows[2]!.endedAt).toBe(rows[2]!.startedAt); // answered at once
    expect(inspect([ev(0, "task_created")]).delegations).toEqual([]);
  });

  it("gives a retried task's report to its newest hand-off of the same call id", () => {
    const rows = inspect([
      ev(1, "delegated", { id: "c1", agent: "Researcher", task_id: "old" }),
      ev(1, "delegation_finished", { id: "c1", agent: "Researcher", state: "canceled" }),
      ev(2, "delegated", { id: "c1", agent: "Researcher", task_id: "new" }),
      ev(2, "delegation_finished", { id: "c1", agent: "Researcher", state: "completed" }),
    ]).delegations;
    expect(rows.map((r) => [r.taskId, r.state])).toEqual([
      ["old", "canceled"],
      ["new", "completed"],
    ]);
  });
});
