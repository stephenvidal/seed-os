import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { mockApi, renderApp } from "../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };
const MODELS = {
  status: 200,
  body: {
    provider: "ollama",
    default_model: null,
    models: [{ id: "m-small", provider: "ollama", size_bytes: null }],
  },
};

function sse(...events: [string, unknown][]): string {
  return events
    .map(([e, d], i) => `id: ${i}\nevent: ${e}\ndata: ${JSON.stringify(d)}\n\n`)
    .join("");
}

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

  it("streams a run: tool activity, final text, and usage", async () => {
    const body = sse(
      ["run_id", { run_id: "r1" }],
      ["run_started", {}],
      ["step_started", { step: 1 }],
      ["tool_call", { id: "call_0", name: "write_file", arguments: { path: "a.txt" } }],
      ["tool_result", { id: "call_0", ok: true, duration_ms: 3 }],
      ["step_started", { step: 2 }],
      ["text_delta", { text: "Created " }],
      ["text_delta", { text: "a.txt" }],
      [
        "run_finished",
        { termination: "completed", steps: 2, usage: { input_tokens: 40, output_tokens: 7 } },
      ],
    );
    const fetchSpy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
    });
    fetchSpy.mockImplementation(async (input, init) => {
      const key = `${init?.method ?? "GET"} ${String(input)}`;
      if (key === "GET /api/v1/auth/me") return new Response(JSON.stringify(ME.body));
      if (key === "GET /api/v1/models") return new Response(JSON.stringify(MODELS.body));
      if (key === "POST /api/v1/runs") return new Response(body, { status: 200 });
      throw new TypeError(`unmocked ${key}`);
    });
    const user = userEvent.setup();
    renderApp(<App />, "/chat");
    await screen.findByRole("option", { name: "m-small" });
    await user.type(screen.getByLabelText("Message"), "make a file{Enter}");

    expect(await screen.findByText("Created a.txt")).toBeInTheDocument();
    expect(screen.getByText(/completed · 2 steps · 40 in \/ 7 out tokens/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /used 1 tool/i }));
    expect(screen.getByText("write_file")).toBeInTheDocument();

    const sent = JSON.parse(
      String(fetchSpy.mock.calls.find((c) => String(c[0]) === "/api/v1/runs")?.[1]?.body),
    );
    expect(sent).toEqual({ model: "m-small", prompt: "make a file", history: [] });
    vi.restoreAllMocks();
  });

  it("shows a failed run's reason", async () => {
    const body = sse([
      "run_finished",
      { termination: "provider_error", steps: 1, error: "auth: Unauthorized" },
    ]);
    const spy = mockApi({});
    spy.mockImplementation(async (input, init) => {
      const key = `${init?.method ?? "GET"} ${String(input)}`;
      if (key === "GET /api/v1/auth/me") return new Response(JSON.stringify(ME.body));
      if (key === "GET /api/v1/models") return new Response(JSON.stringify(MODELS.body));
      return new Response(body);
    });
    const user = userEvent.setup();
    renderApp(<App />, "/chat");
    await screen.findByRole("option", { name: "m-small" });
    await user.type(screen.getByLabelText("Message"), "hi{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("auth: Unauthorized");
  });
});
