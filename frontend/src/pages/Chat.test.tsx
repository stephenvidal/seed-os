import { act, screen, waitFor, within } from "@testing-library/react";
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

const turn = (over: Record<string, unknown> = {}) => ({
  id: "t1",
  title: "Plan my week",
  model: "m-default",
  prompt: "Plan my week",
  state: "completed",
  attempt: 1,
  max_attempts: 3,
  cancel_requested: false,
  termination: "completed",
  error: null,
  result_text: "Here is **the plan**.",
  usage: { input_tokens: 30, output_tokens: 5 },
  last_seq: 6,
  resumable_from_step: null,
  created_at: "2026-10-29T01:00:00Z",
  updated_at: "2026-10-29T01:00:00Z",
  started_at: "2026-10-29T01:00:00Z",
  finished_at: "2026-10-29T01:00:05Z",
  conversation_id: "c1",
  turn: 1,
  ...over,
});

const conversation = {
  id: "c1",
  owner: "admin",
  title: "Plan my week",
  model: "m-default",
  created_at: "2026-10-29T01:00:00Z",
  updated_at: "2026-10-29T01:00:05Z",
};
const summary = { ...conversation, turns: 1, last_state: "completed" };

const bodyOf = (spy: ReturnType<typeof mockApi>, method: string, url: string) => {
  const call = spy.mock.calls.find((c) => c[1]?.method === method && String(c[0]) === url);
  return (
    call && {
      body: JSON.parse(String(call[1]?.body)) as unknown,
      headers: call[1]?.headers as Record<string, string>,
    }
  );
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Chat", () => {
  it("explains when no provider is configured", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": {
        status: 503,
        body: { error: { code: "provider_not_configured", message: "Set SEED_OLLAMA_API_KEY." } },
      },
    });
    renderApp(<App />, "/chat");
    expect(await screen.findByText("No model provider configured")).toBeInTheDocument();
    expect(screen.getByText("Set SEED_OLLAMA_API_KEY.")).toBeInTheDocument();
  });

  it("starts a saved conversation and streams the reply live", async () => {
    let detail = { conversation, turns: [turn({ state: "queued", result_text: null })] };
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [] },
      "POST /api/v1/conversations": () => ({ status: 201, body: detail }),
      "GET /api/v1/conversations/c1": () => ({ status: 200, body: detail }),
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/chat");
    expect(await screen.findByText("Saved conversations appear here.")).toBeInTheDocument();
    await screen.findByRole("option", { name: "m-default" });
    await user.type(screen.getByLabelText("Message"), "Plan my week{Enter}");

    await waitFor(() => expect(FakeEventSource.last?.url).toBe("/api/v1/tasks/t1/stream?after=0"));
    const sent = bodyOf(spy, "POST", "/api/v1/conversations");
    expect(sent?.body).toEqual({ model: "m-default", prompt: "Plan my week" });
    expect(sent?.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.getByText("Waiting for a worker…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();

    const es = FakeEventSource.last!;
    act(() => {
      es.emit(1, "task_created", {}, 0);
      es.emit(2, "attempt_started", {});
      es.emit(3, "step_started", { step: 1 });
      es.emit(4, "tool_call", { id: "call_0", name: "write_file", arguments: { path: "a.md" } });
      es.emit(5, "tool_result", { id: "call_0", ok: true, duration_ms: 3 });
      es.emit(6, "step_started", { step: 2 });
      es.emit(7, "text_delta", { text: "Here is **the" });
      es.emit(7, "text_delta", { text: "Here is **the" }); // a replayed duplicate is ignored
      es.emit(8, "text_delta", { text: " plan**." });
    });
    const strong = screen.getByText("the plan");
    expect(strong.tagName).toBe("STRONG"); // rendered as Markdown
    expect(strong.closest("p")?.textContent).toBe("Here is the plan.");
    await user.click(screen.getByRole("button", { name: /used 1 tool/i }));
    expect(screen.getByText("write_file")).toBeInTheDocument();

    detail = { conversation, turns: [turn()] };
    act(() => es.end());
    expect(await screen.findByText("30 in / 5 out tokens")).toBeInTheDocument();
    expect(es.closed).toBe(true);
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("shows a saved conversation, never renders raw HTML, and sends the next message", async () => {
    const answer =
      'Hi <img src="x" alt="injected"> [click](javascript:alert(1)) [ok](https://a.example)';
    let detail = { conversation, turns: [turn({ result_text: answer })] };
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [summary] },
      "GET /api/v1/conversations/c1": () => ({ status: 200, body: detail }),
      "POST /api/v1/conversations/c1/turns": () => {
        const next = turn({ id: "t2", turn: 2, prompt: "And next week?", state: "queued" });
        detail = {
          conversation: { ...conversation, model: "m-small" },
          turns: [...detail.turns, next],
        };
        return { status: 201, body: next };
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/chat/c1");

    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    expect(await within(nav).findByRole("link", { name: "Plan my week" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByText(/Hi/)).toBeInTheDocument();
    expect(screen.queryByAltText("injected")).toBeNull();
    expect(screen.getByText("click")).not.toHaveAttribute(
      "href",
      expect.stringContaining("javascript"),
    );
    expect(screen.getByRole("link", { name: "ok" })).toHaveAttribute(
      "rel",
      expect.stringContaining("noopener"),
    );

    await screen.findByRole("option", { name: "m-small" });
    await user.selectOptions(screen.getByLabelText("Model"), "m-small");
    await user.type(screen.getByLabelText("Message"), "And next week?{Enter}");
    await waitFor(() => expect(FakeEventSource.last?.url).toBe("/api/v1/tasks/t2/stream?after=0"));
    // The model changed, so the turn says so; otherwise it is left to the conversation.
    expect(bodyOf(spy, "POST", "/api/v1/conversations/c1/turns")?.body).toEqual({
      prompt: "And next week?",
      model: "m-small",
    });
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    // One message at a time: Enter does nothing while the answer is coming.
    await user.type(screen.getByLabelText("Message"), "Too soon{Enter}");
    const turns = spy.mock.calls.filter((c) => String(c[0]) === "/api/v1/conversations/c1/turns");
    expect(turns).toHaveLength(1);
  });

  it("stops an answer, and offers to try a failed last turn again", async () => {
    let detail = { conversation, turns: [turn({ state: "running", result_text: null })] };
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [summary] },
      "GET /api/v1/conversations/c1": () => ({ status: 200, body: detail }),
      "POST /api/v1/tasks/t1/cancel": () => {
        detail = {
          conversation,
          turns: [
            turn({
              state: "failed",
              termination: "provider_error",
              error: "auth: Unauthorized",
              result_text: null,
            }),
          ],
        };
        return { status: 200, body: detail.turns[0] };
      },
      "POST /api/v1/tasks/t1/retry": { status: 200, body: turn({ state: "queued" }) },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/chat/c1");

    await user.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("auth: Unauthorized");
    await user.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() =>
      expect(spy.mock.calls.some((c) => String(c[0]) === "/api/v1/tasks/t1/retry")).toBe(true),
    );
  });

  it("asks before running a command and sends the decision", async () => {
    const detail = { conversation, turns: [turn({ state: "running", result_text: null })] };
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [summary] },
      "GET /api/v1/conversations/c1": () => ({ status: 200, body: detail }),
      "POST /api/v1/tasks/t1/decision": { status: 200, body: turn({ state: "queued" }) },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    FakeEventSource.last = undefined;
    renderApp(<App />, "/chat/c1");
    await waitFor(() => expect(FakeEventSource.last?.url).toBe("/api/v1/tasks/t1/stream?after=0"));
    const es = FakeEventSource.last!;
    act(() => {
      es.emit(1, "step_started", { step: 1 });
      es.emit(2, "tool_call", {
        id: "call_0",
        name: "run_command",
        arguments: { command: "rm -rf build" },
      });
      es.emit(3, "approval_requested", {
        id: "call_0",
        name: "run_command",
        arguments: { command: "rm -rf build" },
      });
    });
    const prompt = screen.getByRole("region", { name: "Approval needed" });
    expect(within(prompt).getByText("rm -rf build")).toBeInTheDocument();
    expect(screen.queryByText("Working…")).toBeNull();

    await user.click(within(prompt).getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(bodyOf(spy, "POST", "/api/v1/tasks/t1/decision")?.body).toEqual({
        call_id: "call_0",
        approve: true,
      }),
    );
    // Decided once: neither button can send a second decision.
    expect(within(prompt).getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(within(prompt).getByRole("button", { name: "Deny" })).toBeDisabled();
    act(() => es.emit(4, "approval_decided", { id: "call_0", approved: true, by: "admin" }));
    expect(screen.queryByRole("region", { name: "Approval needed" })).toBeNull();
  });

  it("says when a conversation does not exist", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [] },
      "GET /api/v1/conversations/nope": {
        status: 404,
        body: { error: { code: "not_found", message: "No such conversation." } },
      },
    });
    renderApp(<App />, "/chat/nope");
    expect(await screen.findByText("No such conversation")).toBeInTheDocument();
  });
});
