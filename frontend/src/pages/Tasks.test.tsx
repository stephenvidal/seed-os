import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { FakeEventSource } from "../test/eventsource";
import { mockApi, renderApp } from "../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };
const MODELS = {
  status: 200,
  body: {
    provider: "ollama",
    default_model: "m-default",
    models: [
      { id: "m-small", provider: "ollama", size_bytes: null },
      { id: "m-default", provider: "ollama", size_bytes: null },
    ],
  },
};

const task = (over: Record<string, unknown> = {}) => ({
  id: "t1",
  title: "Write the report",
  model: "m-default",
  prompt: "Write the report",
  state: "running",
  attempt: 1,
  max_attempts: 3,
  cancel_requested: false,
  termination: null,
  error: null,
  result_text: null,
  usage: { input_tokens: 0, output_tokens: 0 },
  last_seq: 3,
  resumable_from_step: null,
  created_at: "2026-10-28T22:00:00Z",
  updated_at: "2026-10-28T22:00:00Z",
  started_at: "2026-10-28T22:00:00Z",
  finished_at: null,
  ...over,
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Tasks", () => {
  it("explains when the database is not configured", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks?limit=100": {
        status: 503,
        body: { error: { code: "database_not_configured", message: "Set SEED_DATABASE_URL." } },
      },
    });
    renderApp(<App />, "/tasks");
    expect(await screen.findByText("Tasks need a database")).toBeInTheDocument();
    expect(screen.getByText("Set SEED_DATABASE_URL.")).toBeInTheDocument();
  });

  it("lists tasks and creates one with an idempotency key", async () => {
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/tasks?limit=100": {
        status: 200,
        body: [task({ state: "completed", usage: { input_tokens: 9, output_tokens: 1 } })],
      },
      "POST /api/v1/tasks": { status: 201, body: task({ id: "t2", state: "queued" }) },
      "GET /api/v1/tasks/t2": { status: 200, body: task({ id: "t2", state: "queued" }) },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/tasks");

    expect(await screen.findByText("Write the report")).toBeInTheDocument();
    expect(screen.getByText("9 in / 1 out tokens")).toBeInTheDocument();
    await screen.findByRole("option", { name: "m-default" });
    await user.type(screen.getByLabelText("What should SEED do?"), "Summarise the repo");
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() => expect(FakeEventSource.last?.url).toBe("/api/v1/tasks/t2/stream?after=0"));
    const post = spy.mock.calls.find((c) => c[1]?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      model: "m-default",
      prompt: "Summarise the repo",
    });
    const headers = post?.[1]?.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("follows a running task live and cancels it", async () => {
    let current = task();
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks/t1": () => ({ status: 200, body: current }),
      "POST /api/v1/tasks/t1/cancel": () => {
        current = task({ cancel_requested: true });
        return { status: 200, body: current };
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/tasks/t1");
    expect(await screen.findByRole("heading", { name: "Write the report" })).toBeInTheDocument();
    const es = FakeEventSource.last!;
    expect(es.url).toBe("/api/v1/tasks/t1/stream?after=0");

    act(() => {
      es.emit(1, "task_created", {}, 0);
      es.emit(2, "attempt_started", { resumed_at_step: null });
      es.emit(3, "step_started", { step: 1 });
      es.emit(4, "text_delta", { text: "Working on " });
      es.emit(5, "text_delta", { text: "it" });
      es.emit(5, "text_delta", { text: "it" }); // a replayed duplicate is ignored
    });
    expect(screen.getByText("Working on it")).toBeInTheDocument();
    expect(screen.getByText("Attempt 1 started")).toBeInTheDocument();
    expect(screen.getByText("live")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("canceling")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    current = task({ state: "canceled", termination: "cancelled", cancel_requested: true });
    act(() => {
      es.emit(6, "run_finished", { termination: "cancelled" });
      es.end();
    });
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(es.closed).toBe(true);
    expect(screen.getByText("interrupted")).toBeInTheDocument();
  });

  it("shows a queued task's cancel even though the task finishes first", async () => {
    let current = task({ state: "queued", attempt: 0 });
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks/t1": () => ({ status: 200, body: current }),
      "POST /api/v1/tasks/t1/cancel": () => {
        current = task({ state: "canceled", attempt: 0, cancel_requested: true });
        return { status: 200, body: current };
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/tasks/t1");
    expect(await screen.findByRole("heading", { name: "Write the report" })).toBeInTheDocument();
    const es = FakeEventSource.last!;
    act(() => es.emit(1, "task_created", {}, 0));

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(es.closed).toBe(false); // the cancel event has not arrived yet
    act(() => {
      es.emit(2, "cancel_requested", { state: "canceled" }, 0);
      es.end();
    });
    expect(screen.getByText("Canceled before it started")).toBeInTheDocument();
    expect(es.closed).toBe(true);
  });
});
