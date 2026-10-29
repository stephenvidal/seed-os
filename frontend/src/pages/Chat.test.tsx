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
  summary_of: null,
  summary: null,
  ...over,
  versions: (over.versions as string[] | undefined) ?? [String(over.id ?? "t1")],
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

  it("marks where the model starts seeing earlier messages as a summary", async () => {
    const detail = {
      conversation,
      turns: [
        turn({ id: "t1", summary: "Older turn summary" }),
        turn({ id: "t2", turn: 2, summary: "Newer summary" }),
        turn({ id: "t3", turn: 3, summary_of: "t2" }),
      ],
    };
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [summary] },
      "GET /api/v1/conversations/c1": { status: 200, body: detail },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/chat/c1");

    const note = await screen.findByText("The model now sees the messages above as a summary");
    expect(screen.getAllByText(/as a summary/)).toHaveLength(1); // only where it applies now
    expect(screen.queryByText("Older turn summary")).toBeNull();
    await user.click(note);
    expect(screen.getByText("Newer summary")).toBeVisible();
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

  it("renames a conversation, and Escape leaves it as it was", async () => {
    let current = conversation;
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": () => ({
        status: 200,
        body: [{ ...summary, title: current.title }],
      }),
      "GET /api/v1/conversations/c1": () => ({
        status: 200,
        body: { conversation: current, turns: [turn()] },
      }),
      "PATCH /api/v1/conversations/c1": () => {
        current = { ...conversation, title: "Week plan" };
        return { status: 200, body: current };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/chat/c1");

    await user.click(await screen.findByRole("button", { name: "Rename conversation" }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("heading", { name: "Plan my week" })).toBeInTheDocument();
    expect(spy.mock.calls.some((c) => c[1]?.method === "PATCH")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Rename conversation" }));
    const input = screen.getByLabelText("Conversation title");
    expect(input).toHaveValue("Plan my week");
    await user.clear(input);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.type(input, "  Week   plan {Enter}");
    expect(await screen.findByRole("heading", { name: "Week plan" })).toBeInTheDocument();
    expect(bodyOf(spy, "PATCH", "/api/v1/conversations/c1")?.body).toEqual({ title: "Week plan" });
    const nav = screen.getByRole("navigation", { name: "Conversations" });
    expect(await within(nav).findByRole("link", { name: "Week plan" })).toBeInTheDocument();
  });

  it("deletes a conversation only after a confirm, then goes back to a new chat", async () => {
    let list = [summary];
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": () => ({ status: 200, body: list }),
      "GET /api/v1/conversations/c1": {
        status: 200,
        body: { conversation, turns: [turn(), turn({ id: "t2", turn: 2 })] },
      },
      "DELETE /api/v1/conversations/c1": () => {
        list = [];
        return { status: 204 };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/chat/c1");

    await user.click(await screen.findByRole("button", { name: "Delete conversation" }));
    const confirm = screen.getByRole("alertdialog", { name: "Delete conversation" });
    expect(confirm).toHaveTextContent("its 2 messages");
    await user.click(within(confirm).getByRole("button", { name: "Keep" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(spy.mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Delete conversation" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByText("Ask SEED to do something")).toBeInTheDocument();
    expect(await screen.findByText("Saved conversations appear here.")).toBeInTheDocument();
    expect(spy.mock.calls.filter((c) => c[1]?.method === "DELETE")).toHaveLength(1);
  });

  it("cannot delete while answering, and shows a refusal", async () => {
    let state = "running";
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [summary] },
      "GET /api/v1/conversations/c1": () => ({
        status: 200,
        body: { conversation, turns: [turn({ state, result_text: null })] },
      }),
      "POST /api/v1/tasks/t1/cancel": () => {
        state = "canceled";
        return { status: 200, body: turn({ state }) };
      },
      "DELETE /api/v1/conversations/c1": {
        status: 409,
        body: {
          error: { code: "turn_in_progress", message: "A message is still being answered." },
        },
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/chat/c1");

    expect(await screen.findByRole("button", { name: "Delete conversation" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Delete conversation" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Delete conversation" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("still being answered");
    expect(screen.getByRole("heading", { name: "Plan my week" })).toBeInTheDocument();
  });

  it("searches conversations after a pause in typing", async () => {
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": {
        status: 200,
        body: [summary, { ...summary, id: "c2", title: "Lisbon trip" }],
      },
      "GET /api/v1/conversations?limit=200&q=lisbon%20%25": {
        status: 200,
        body: [{ ...summary, id: "c2", title: "Lisbon trip" }],
      },
      "GET /api/v1/conversations?limit=200&q=zzz": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/chat");

    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    expect(await within(nav).findByRole("link", { name: "Plan my week" })).toBeInTheDocument();
    await user.type(
      within(nav).getByRole("searchbox", { name: "Search conversations" }),
      " lisbon % ",
    );
    await waitFor(() =>
      expect(within(nav).queryByRole("link", { name: "Plan my week" })).toBeNull(),
    );
    expect(within(nav).getByRole("link", { name: "Lisbon trip" })).toBeInTheDocument();
    // One request for the finished phrase, not one per key.
    const searches = spy.mock.calls.filter((c) => String(c[0]).includes("&q="));
    expect(searches.map((c) => String(c[0]))).toEqual([
      "/api/v1/conversations?limit=200&q=lisbon%20%25",
    ]);

    await user.clear(within(nav).getByRole("searchbox"));
    await user.type(within(nav).getByRole("searchbox"), "zzz");
    expect(await within(nav).findByText("No conversations match “zzz”.")).toBeInTheDocument();
  });

  it("edits a message as a new version, keeps the old one, and switches back", async () => {
    const t1 = turn({ prompt: "Plan my week", result_text: "Week plan." });
    const t2 = turn({ id: "t2", turn: 2, prompt: "Add gym", result_text: "Gym added." });
    const v2 = turn({ id: "v2", turn: 2, prompt: "Add yoga", result_text: "Yoga added." });
    let detail = { conversation, turns: [t1, t2] };
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [summary] },
      "GET /api/v1/conversations/c1": () => ({ status: 200, body: detail }),
      "POST /api/v1/conversations/c1/turns/t2/versions": () => {
        detail = { conversation, turns: [t1, { ...v2, versions: ["t2", "v2"] }] };
        return { status: 201, body: { ...v2, state: "queued", result_text: null } };
      },
      "PUT /api/v1/conversations/c1/shown": () => {
        detail = { conversation, turns: [t1, { ...t2, versions: ["t2", "v2"] }] };
        return { status: 200, body: detail };
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/chat/c1");

    await screen.findByText("Gym added.");
    expect(screen.queryByRole("button", { name: "Previous version" })).toBeNull();
    await user.click(screen.getAllByRole("button", { name: "Edit" })[1]!);
    await user.keyboard("{Escape}");
    expect(screen.queryByLabelText("Edit message")).toBeNull();
    await user.click(screen.getAllByRole("button", { name: "Edit" })[1]!);
    const box = screen.getByLabelText("Edit message");
    expect(box).toHaveValue("Add gym");
    await user.clear(box);
    await user.type(box, "Add yoga");
    await user.click(screen.getByRole("button", { name: "Send edit" }));

    expect(bodyOf(spy, "POST", "/api/v1/conversations/c1/turns/t2/versions")?.body).toEqual({
      prompt: "Add yoga",
    });
    expect(await screen.findByText("Yoga added.")).toBeInTheDocument();
    expect(screen.queryByText("Gym added.")).toBeNull();
    expect(screen.getByLabelText("Version 2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next version" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Previous version" }));
    expect(await screen.findByText("Gym added.")).toBeInTheDocument();
    expect(screen.getByLabelText("Version 1 of 2")).toBeInTheDocument();
    expect(bodyOf(spy, "PUT", "/api/v1/conversations/c1/shown")?.body).toEqual({
      turn_id: "t2",
    });
  });

  it("regenerates an answer, and offers nothing new while one is coming", async () => {
    const t2 = turn({ id: "t2", turn: 2, prompt: "Add gym", result_text: "Gym added." });
    const r1 = turn({ id: "r1", state: "running", result_text: null, versions: ["t1", "r1"] });
    let detail = { conversation, turns: [turn(), t2] };
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [summary] },
      "GET /api/v1/conversations/c1": () => ({ status: 200, body: detail }),
      "POST /api/v1/conversations/c1/turns/t1/versions": () => {
        detail = { conversation, turns: [r1] };
        return { status: 201, body: { ...r1, state: "queued" } };
      },
    });
    vi.stubGlobal("EventSource", FakeEventSource);
    const user = userEvent.setup();
    renderApp(<App />, "/chat/c1");

    await screen.findByText("Gym added.");
    await user.click(screen.getAllByRole("button", { name: "Regenerate" })[0]!);
    expect(bodyOf(spy, "POST", "/api/v1/conversations/c1/turns/t1/versions")?.body).toEqual({});
    // The later message belongs to the older version now, so it leaves the view.
    await waitFor(() => expect(screen.queryByText("Add gym")).toBeNull());
    expect(screen.getByLabelText("Version 2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous version" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull(); // not finished yet
  });
});
