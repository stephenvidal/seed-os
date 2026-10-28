import { describe, expect, it } from "vitest";
import { toTimeline } from "./tasks";
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
});
