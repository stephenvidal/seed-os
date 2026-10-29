import { describe, expect, it } from "vitest";
import { pendingApproval, pendingDelegation, toTimeline } from "./tasks";
import type { TaskEvent } from "./tasks";

let seq = 0;
const ev = (type: string, data: Record<string, unknown> = {}, attempt = 1): TaskEvent => ({
  seq: ++seq,
  attempt,
  type,
  data,
  created_at: "2026-10-28T22:00:00Z",
});

describe("toTimeline", () => {
  it("folds a crash-and-resume run into notes and steps", () => {
    seq = 0;
    const items = toTimeline([
      ev("task_created", {}, 0),
      ev("attempt_started", { resumed_at_step: null }),
      ev("run_started"),
      ev("step_started", { step: 1 }),
      ev("step_completed", { step: 1, usage: { input_tokens: 100, output_tokens: 10 } }),
      ev("tool_call", { step: 1, id: "call_0", name: "write_file", arguments: { path: "a" } }),
      ev("tool_result", { step: 1, id: "call_0", ok: true, duration_ms: 2 }),
      ev("step_started", { step: 2 }),
      ev("attempt_started", { resumed_at_step: 1 }, 2),
      ev("step_started", { step: 2 }, 2),
      ev("text_delta", { text: "Wrote " }, 2),
      ev("text_delta", { text: "a" }, 2),
      ev("step_completed", { step: 2, usage: { input_tokens: 150, output_tokens: 5 } }, 2),
      ev("run_finished", { termination: "completed" }, 2),
    ]);
    expect(items.map((i) => (i.kind === "note" ? i.text : `step ${i.step}/${i.attempt}`))).toEqual([
      "Created",
      "Attempt 1 started",
      "step 1/1",
      "step 2/1",
      "Attempt 2 resumed after step 1",
      "step 2/2",
      "Finished",
    ]);
    const [, , first, interrupted, , last] = items;
    expect(first).toMatchObject({ done: true, tokens: { input: 100, output: 10 } });
    expect(first?.kind === "step" && first.tools[0]).toMatchObject({
      name: "write_file",
      ok: true,
    });
    expect(interrupted).toMatchObject({ kind: "step", done: false });
    expect(last).toMatchObject({ text: "Wrote a", done: true });
  });

  it("describes failures and lifecycle events plainly", () => {
    seq = 0;
    const notes = toTimeline([
      ev("provider_retry", { kind: "rate_limited", delay_s: 1 }),
      ev("run_finished", { termination: "provider_error", error: "auth: bad key" }),
      ev("task_requeued"),
      ev("cancel_requested", { state: "canceled" }),
      ev("lease_expired", { state: "failed" }),
    ]).map((i) => i.kind === "note" && [i.tone, i.text]);
    expect(notes).toEqual([
      ["warning", "Model provider rate_limited; retrying in 1 s"],
      ["danger", "Stopped: model provider error (auth: bad key)"],
      ["neutral", "Queued again for retry"],
      ["neutral", "Canceled before it started"],
      ["danger", "Worker stopped responding on every attempt; task failed"],
    ]);
  });

  it("says which files were saved, skipped, put back or not saved", () => {
    seq = 0;
    const saved = Array.from({ length: 7 }, (_, i) => ({
      path: `f${i}.txt`,
      version: i + 1,
      deleted: i === 1,
    }));
    const notes = toTimeline([
      ev("workspace_restored", { files: 1 }),
      ev("artifacts_saved", {
        saved,
        skipped: [{ path: "big.bin", reason: "too_large" }],
        truncated: true,
      }),
      ev("artifacts_saved", { saved: [saved[0]], skipped: [], truncated: false }),
      ev("artifacts_failed", { stage: "save", error: "disk full" }),
      ev("artifacts_failed", { stage: "restore", error: "gone" }),
    ]).map((i) => i.kind === "note" && [i.tone, i.text]);
    expect(notes).toEqual([
      ["neutral", "Workspace was empty; put back 1 saved file"],
      [
        "accent",
        "Saved 7 files: f0.txt v1, f1.txt (deleted), f2.txt v3, f3.txt v4, f4.txt v5, and 2 more",
      ],
      ["warning", "Not saved: big.bin (too large)"],
      ["warning", "Too many files to save them all"],
      ["accent", "Saved 1 file: f0.txt v1"],
      ["danger", "Saving files failed: disk full"],
      ["danger", "Restoring files failed: gone"],
    ]);
  });

  it("says when earlier turns were summarized for the model", () => {
    seq = 0;
    const notes = toTimeline([
      ev("context_summarized", { through: "t1", turns: 3 }),
      ev("context_summarized", { through: "t1", turns: 0 }),
      ev("summary_failed", { error: "timeout" }),
    ]).map((i) => i.kind === "note" && [i.tone, i.text]);
    expect(notes).toEqual([
      ["neutral", "Summarized 3 earlier turns for the model"],
      ["neutral", "Gave the model the saved summary of earlier turns"],
      ["warning", "Could not summarize earlier turns: timeout"],
    ]);
  });
});

describe("approvals", () => {
  const ask = (id: string) =>
    ev("approval_requested", { id, name: "run_command", arguments: { command: "make" } });

  it("finds the call a task waits on until it is decided or canceled", () => {
    expect(pendingApproval([ev("task_created")])).toBeNull();
    expect(pendingApproval([ask("c1")])).toEqual({
      id: "c1",
      name: "run_command",
      arguments: { command: "make" },
    });
    expect(pendingApproval([ask("c1"), ev("approval_decided", { id: "c1" })])).toBeNull();
    expect(pendingApproval([ask("c1"), ev("cancel_requested")])).toBeNull();
    expect(pendingApproval([ask("c1"), ev("approval_decided"), ask("c2")])?.id).toBe("c2");
  });

  it("gives a step's paused call its result after the decision", () => {
    const items = toTimeline([
      ev("step_started", { step: 1 }),
      ev("tool_call", { id: "c1", name: "run_command", arguments: {} }),
      ask("c1"),
      ev("approval_decided", { id: "c1", approved: false, by: "admin" }),
      ev("attempt_started", { resumed_at_step: 1 }),
      ev("tool_result", { id: "c1", ok: false, error_kind: "denied", error: "denied" }),
      ev("tool_call", { id: "c2", name: "list_files", arguments: {} }),
    ]);
    const step = items.find((i) => i.kind === "step");
    expect(step?.kind === "step" && step.tools.map((t) => [t.id, t.ok])).toEqual([
      ["c1", false],
      ["c2", undefined],
    ]);
  });

  it("notes the request, the pause and the decision in the timeline", () => {
    const notes = toTimeline([
      ask("c1"),
      ev("run_finished", { termination: "awaiting_approval" }),
      ev("approval_decided", { id: "c1", approved: false, by: "admin" }),
    ]).map((i) => (i.kind === "note" ? [i.tone, i.text] : null));
    expect(notes).toEqual([
      ["warning", "Waiting for your approval to run run_command"],
      ["warning", "Paused for your approval"],
      ["neutral", "Denied by admin"],
    ]);
  });
});

describe("delegation", () => {
  const handed = ev("delegated", { id: "c1", agent: "Researcher", task_id: "t9" });

  it("says when work went to an agent and how it came back", () => {
    seq = 0;
    const notes = toTimeline([
      handed,
      ev("delegation_finished", {
        id: "c1",
        agent: "Researcher",
        task_id: "t9",
        state: "completed",
      }),
      ev("delegation_finished", { id: "c2", agent: "Coder", task_id: "t8", state: "failed" }),
      ev("delegation_refused", { id: "c3", reason: "No agent named 'X'." }),
    ]).map((i) => i.kind === "note" && [i.tone, i.text]);
    expect(notes).toEqual([
      ["neutral", "Handed to Researcher as a task of its own"],
      ["accent", "Researcher reported back"],
      ["warning", "Coder stopped: failed"],
      ["warning", "Not delegated: No agent named 'X'."],
    ]);
  });

  it("finds the agent task a task waits for until it reports back or is canceled", () => {
    expect(pendingDelegation([ev("task_created")])).toBeNull();
    expect(pendingDelegation([handed])).toEqual({ agent: "Researcher", taskId: "t9" });
    expect(
      pendingDelegation([handed, ev("run_finished", { termination: "awaiting_delegation" })]),
    ).toEqual({ agent: "Researcher", taskId: "t9" });
    expect(pendingDelegation([handed, ev("delegation_finished", { id: "c1" })])).toBeNull();
    expect(pendingDelegation([handed, ev("cancel_requested", {})])).toBeNull();
  });
});
