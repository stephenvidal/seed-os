import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { App } from "../App";
import { mockApi, renderApp } from "../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };

const TASK = {
  id: "t1",
  title: "List the files",
  model: "m-a",
  prompt: "p",
  state: "completed",
  attempt: 2,
  max_attempts: 3,
  cancel_requested: false,
  termination: "completed",
  error: null,
  result_text: "done",
  usage: { input_tokens: 250, output_tokens: 50 },
  last_seq: 9,
  resumable_from_step: 1,
  created_at: "2026-10-29T12:00:00Z",
  updated_at: "2026-10-29T12:00:30Z",
  started_at: "2026-10-29T12:00:01Z",
  finished_at: "2026-10-29T12:00:31Z",
  conversation_id: "c1",
  turn: 1,
  awaiting_approval: null,
};

const e = (seq: number, attempt: number, type: string, data: Record<string, unknown> = {}) => ({
  seq,
  attempt,
  type,
  data,
  created_at: `2026-10-29T12:00:${String(seq).padStart(2, "0")}Z`,
});

// Two pages: the page must keep reading until it reaches last_seq.
const PAGE1 = [
  e(1, 0, "task_created"),
  e(2, 1, "attempt_started", { worker: "w-1", resumed_at_step: null }),
  e(3, 1, "step_started", { step: 1 }),
  e(4, 1, "text_delta", { text: "Hi" }),
  e(5, 1, "step_completed", {
    step: 1,
    finish_reason: "tool_calls",
    usage: { input_tokens: 100, output_tokens: 20 },
    latency_ms: 1500,
    tool_calls: 1,
  }),
  e(6, 1, "tool_call", { step: 1, id: "c1", name: "run_command", arguments: { command: "ls" } }),
];
const PAGE2 = [
  e(7, 1, "tool_result", { step: 1, id: "c1", ok: true, duration_ms: 40 }),
  e(8, 1, "checkpoint_saved", { steps: 1, pending: 0 }),
  e(9, 1, "run_finished", { termination: "completed" }),
];

afterEach(() => vi.restoreAllMocks());

describe("Inspector", () => {
  it("lists tasks to inspect", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks?limit=100": { status: 200, body: [TASK] },
    });
    renderApp(<App />, "/inspector");
    const link = await screen.findByRole("link", { name: /List the files/ });
    expect(link).toHaveAttribute("href", "/inspector/t1");
    expect(screen.getByText(/does not store model reasoning/)).toBeInTheDocument();
  });

  it("says plainly when nothing has run", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks?limit=100": { status: 200, body: [] },
    });
    renderApp(<App />, "/inspector");
    expect(await screen.findByText("No executions recorded")).toBeInTheDocument();
  });

  it("shows how a task ran, from every page of its events", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks/t1": { status: 200, body: TASK },
      "GET /api/v1/tasks/t1/events?after=0&limit=1000": {
        status: 200,
        body: { events: PAGE1, last_seq: 9, state: "completed" },
      },
      "GET /api/v1/tasks/t1/events?after=6&limit=1000": {
        status: 200,
        body: { events: PAGE2, last_seq: 9, state: "completed" },
      },
    });
    const { container } = renderApp(<App />, "/inspector/t1");

    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(summary).toHaveTextContent("Attempts2 of 3");
    expect(summary).toHaveTextContent("Tokens100 in / 20 out");
    expect(summary).toHaveTextContent("Time in tools40 ms");
    expect(summary).toHaveTextContent("Checkpointafter step 1");
    expect(screen.getByRole("link", { name: "Open chat" })).toHaveAttribute("href", "/chat/c1");

    const attempts = screen.getByRole("region", { name: "Attempts" });
    expect(within(attempts).getAllByRole("row")[1]).toHaveTextContent("w-1");
    expect(within(attempts).getAllByRole("row")[1]).toHaveTextContent("completed");

    const steps = screen.getByRole("region", { name: "Model steps" });
    expect(within(steps).getAllByRole("row")[1]).toHaveTextContent("1.5 s");

    const tools = screen.getByRole("region", { name: "Tool calls" });
    const call = within(tools).getByRole("row", { name: /run_command/ });
    expect(call).toHaveTextContent('{"command":"ls"}');
    expect(call).toHaveTextContent("ok");

    const checkpoints = screen.getByRole("region", { name: "Checkpoints" });
    expect(within(checkpoints).getAllByRole("row")).toHaveLength(2);

    // Text chunks are counted, not listed; everything else is.
    const log = screen.getByRole("region", { name: "Event log" });
    expect(within(log).getAllByRole("listitem")).toHaveLength(8);
    expect(log).toHaveTextContent("run_finished");
    expect(log).not.toHaveTextContent("text_delta");
    expect(await axe(container)).toHaveNoViolations();
  });

  it("explains a task that no longer exists", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks/gone": {
        status: 404,
        body: { error: { code: "not_found", message: "No such task." } },
      },
    });
    renderApp(<App />, "/inspector/gone");
    expect(await screen.findByText("No such task")).toBeInTheDocument();
  });
});
