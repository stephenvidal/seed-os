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

  it("starts a task in the project it was opened from, and links back to it", async () => {
    const projects = {
      status: 200,
      body: [
        { id: "p1", name: "Garden" },
        { id: "p2", name: "Other" },
      ],
    };
    const created = task({ id: "t2", state: "queued", project_id: "p1", conversation_id: null });
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/projects": projects,
      "GET /api/v1/tasks?limit=100": { status: 200, body: [] },
      "POST /api/v1/tasks": { status: 201, body: created },
      "GET /api/v1/tasks/t2": { status: 200, body: created },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/tasks?project=p1");

    await screen.findByRole("option", { name: "Garden" });
    expect(screen.getByLabelText("Project")).toHaveValue("p1");
    await screen.findByRole("option", { name: "m-default" });
    await user.type(screen.getByLabelText("What should SEED do?"), "Plan the beds");
    await user.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(FakeEventSource.last?.url).toBe("/api/v1/tasks/t2/stream?after=0"));
    const post = spy.mock.calls.find((c) => c[1]?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      model: "m-default",
      prompt: "Plan the beds",
      project_id: "p1",
    });
    expect(await screen.findByRole("link", { name: "Garden" })).toHaveAttribute(
      "href",
      "/projects/p1",
    );
  });

  it("sends the check written on a new task", async () => {
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/tasks?limit=100": { status: 200, body: [] },
      "POST /api/v1/tasks": { status: 201, body: task({ id: "t2", state: "queued" }) },
      "GET /api/v1/tasks/t2": { status: 200, body: task({ id: "t2", state: "queued" }) },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/tasks");
    await screen.findByRole("option", { name: "m-default" });
    await user.type(screen.getByLabelText("What should SEED do?"), "Fix the tests");
    await user.type(screen.getByLabelText(/Check \(optional\)/), "  pytest -q ");
    await user.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(FakeEventSource.last?.url).toBe("/api/v1/tasks/t2/stream?after=0"));
    const post = spy.mock.calls.find((c) => c[1]?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      model: "m-default",
      prompt: "Fix the tests",
      check: "pytest -q",
    });
  });

  it("shows a failed check with its output and the answer it overruled", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks/t1": {
        status: 200,
        body: task({
          state: "failed",
          termination: "check_failed",
          error: "The check failed: exit code 1.",
          result_text: "All done, it works!",
          check_command: "pytest -q",
          verification: {
            command: "pytest -q",
            passed: false,
            exit_code: 1,
            timed_out: false,
            stdout: "1 failed",
            stderr: "",
            duration_ms: 1200,
          },
        }),
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    renderApp(<App />, "/tasks/t1");
    await screen.findByRole("heading", { name: "Write the report" });
    expect(screen.getByText("pytest -q")).toBeInTheDocument();
    expect(screen.getAllByText("failed")).toHaveLength(2); // the task's state and the check's
    expect(screen.getByText(/Exit code 1/)).toBeInTheDocument();
    expect(screen.getByText("1 failed")).toBeInTheDocument();
    expect(screen.getByText("What SEED said (its check did not agree)")).toBeInTheDocument();
    expect(screen.getByText("All done, it works!")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("The check failed: exit code 1.");
  });

  it("tells a task waiting for an agent from one waiting for you", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/tasks?limit=100": {
        status: 200,
        body: [
          task({
            id: "t1",
            title: "Delegating",
            state: "waiting",
            awaiting_delegation: { id: "c" },
          }),
          task({ id: "t2", title: "Asking", state: "waiting", awaiting_approval: { id: "d" } }),
        ],
      },
    });
    renderApp(<App />, "/tasks");
    const delegating = (await screen.findByText("Delegating")).closest("a")!;
    expect(delegating).toHaveTextContent("with an agent");
    expect(screen.getByText("Asking").closest("a")).toHaveTextContent("needs you");
  });

  it("links an agent's task to the task that handed it over, and back", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks/t9": {
        status: 200,
        body: task({
          id: "t9",
          title: "Researcher: find the questions",
          state: "completed",
          parent_task_id: "t1",
          agent: { id: "a1", name: "Researcher", description: "Reads" },
        }),
      },
      "GET /api/v1/tasks/t1": {
        status: 200,
        body: task({ id: "t1", title: "What is still open?", state: "completed" }),
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    renderApp(<App />, "/tasks/t9");
    const up = await screen.findByRole("link", { name: "What is still open?" });
    expect(up).toHaveAttribute("href", "/tasks/t1");
    expect(screen.getByText("Handed over by")).toBeInTheDocument();
    expect(screen.getByText("Agent")).toBeInTheDocument();
  });

  it("lists the agent tasks a task handed work to, and keeps them after it ends", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks/t1": {
        status: 200,
        body: task({ state: "completed", termination: "completed", result_text: "Done" }),
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    renderApp(<App />, "/tasks/t1");
    await screen.findByRole("heading", { name: "Write the report" });
    expect(screen.queryByRole("list", { name: "Agent tasks" })).toBeNull();
    const es = FakeEventSource.last!;
    act(() => {
      es.emit(1, "delegated", { id: "c", agent: "Researcher", task_id: "t9" });
      es.emit(2, "delegated", { id: "d", agent: "Coder", task_id: "t8" });
    });
    const list = await screen.findByRole("list", { name: "Agent tasks" });
    expect(list).toHaveTextContent("Researcher's task");
    expect(list).toHaveTextContent("working");
    act(() => {
      es.emit(3, "delegation_finished", { id: "c", agent: "Researcher", state: "completed" });
      es.emit(4, "run_finished", { termination: "completed" });
      es.end();
    });
    await waitFor(() => expect(list).toHaveTextContent("reported back"));
    expect(screen.getByRole("link", { name: "Coder's task" })).toHaveAttribute("href", "/tasks/t8");
  });

  it("starts a task's page afresh when moving to another task", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks/t9": {
        status: 200,
        body: task({
          id: "t9",
          title: "Researcher: find it",
          state: "completed",
          parent_task_id: "t1",
        }),
      },
      "GET /api/v1/tasks/t1": {
        status: 200,
        body: task({ id: "t1", title: "What is still open?", state: "completed" }),
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/tasks/t9");
    await screen.findByRole("heading", { name: "Researcher: find it" });
    act(() => FakeEventSource.last!.emit(7, "attempt_started", { resumed_at_step: null }));
    expect(screen.getByText("Attempt 1 started")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "What is still open?" }));
    await screen.findByRole("heading", { name: "What is still open?" });
    expect(screen.queryByText("Attempt 1 started")).toBeNull(); // the other task's events
    await waitFor(() => expect(FakeEventSource.last?.url).toBe("/api/v1/tasks/t1/stream?after=0"));
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

  it("lets you deny the command a waiting task asks to run", async () => {
    const waiting = task({
      state: "waiting",
      awaiting_approval: { id: "call_0", name: "run_command", arguments: { command: "make" } },
    });
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tasks/t1": { status: 200, body: waiting },
      "POST /api/v1/tasks/t1/decision": { status: 200, body: task({ state: "queued" }) },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    FakeEventSource.last = undefined;
    renderApp(<App />, "/tasks/t1");
    expect(await screen.findByText("needs you")).toBeInTheDocument();
    await waitFor(() => expect(FakeEventSource.last).toBeDefined());
    const es = FakeEventSource.last!;
    act(() =>
      es.emit(1, "approval_requested", {
        id: "call_0",
        name: "run_command",
        arguments: { command: "make" },
      }),
    );
    await user.click(screen.getByRole("button", { name: "Deny" }));
    await waitFor(() => {
      const post = spy.mock.calls.find((c) => String(c[0]) === "/api/v1/tasks/t1/decision");
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({ call_id: "call_0", approve: false });
    });
  });
});
