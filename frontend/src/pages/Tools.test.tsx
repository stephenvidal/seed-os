import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { App } from "../App";
import { mockApi, renderApp } from "../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };

const tool = (over: Record<string, unknown> = {}) => ({
  name: "read_file",
  description: "Read a file in the workspace.",
  permission: "read",
  timeout_s: 30,
  max_output_chars: 20000,
  requires_approval: false,
  deferred: false,
  available_in: "Every task and chat turn",
  arguments: [{ name: "path", type: "string", required: true, description: "Where the file is" }],
  ...over,
});

const VIEW = {
  generated_at: "2026-10-29T12:00:00Z",
  window_hours: 24,
  tools: [
    tool(),
    tool({
      name: "run_command",
      description: "Run a shell command in the sandbox.",
      permission: "exec",
      timeout_s: 75,
      requires_approval: true,
      available_in: "Tasks run by a worker with a sandbox (SEED_SANDBOX_URL)",
      arguments: [
        { name: "command", type: "string", required: true, description: "Shell command" },
        { name: "timeout_s", type: "integer", required: false, description: "Seconds" },
      ],
    }),
    tool({ name: "delegate", permission: "exec", deferred: true }),
  ],
  usage: [
    {
      tool: "run_command",
      calls: 5,
      ok: 2,
      failed: 3,
      avg_ms: 1500,
      failures: { denied: 2, tool_error: 1 },
    },
    { tool: "read_file", calls: 1200, ok: 1200, failed: 0, avg_ms: 12, failures: {} },
  ],
};

afterEach(() => vi.restoreAllMocks());

describe("Tools & Skills", () => {
  it("lists each tool with its permission and approval policy, and how they were used", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tools?hours=24": { status: 200, body: VIEW },
    });
    const user = userEvent.setup();
    const { container } = renderApp(<App />, "/tools");
    const list = await screen.findByRole("list", { name: "Tools" });
    const [read, run, delegate] = within(list).getAllByRole("listitem");
    expect(read).toHaveTextContent("read_file");
    expect(read).toHaveTextContent("reads");
    expect(read).toHaveTextContent("runs on its own");
    expect(run).toHaveTextContent("runs code");
    expect(run).toHaveTextContent("asks you first");
    expect(run).toHaveTextContent("SEED_SANDBOX_URL");
    expect(delegate).toHaveTextContent("answered by an agent");

    // The details open on demand.
    await user.click(within(run!).getByText("run_command"));
    expect(run).toHaveTextContent("75 s");
    expect(run).toHaveTextContent("timeout_s (optional)");
    expect(run).toHaveTextContent("command");

    const policy = screen.getByRole("region", { name: "Approval policy" });
    expect(policy).toHaveTextContent("before each call to run_command");
    expect(policy).toHaveTextContent("SEED_APPROVAL_REQUIRED_TOOLS");

    const usage = screen.getByRole("region", { name: "Usage (24h)" });
    expect(within(usage).getByRole("row", { name: /run_command/ })).toHaveTextContent(
      "run_command5231.5 sdenied 2, tool error 1",
    );
    expect(within(usage).getByRole("row", { name: /read_file/ })).toHaveTextContent(
      "read_file1,2001,200012 ms—",
    );
    expect(screen.getByText("No skills yet")).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("says plainly when nothing waits for approval and nothing was used", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tools?hours=24": {
        status: 200,
        body: { ...VIEW, tools: [tool()], usage: [] },
      },
    });
    renderApp(<App />, "/tools");
    expect(await screen.findByText(/No tool waits for approval/)).toBeInTheDocument();
    expect(screen.getByText("No tool calls recorded")).toBeInTheDocument();
  });

  it("explains that usage needs a database", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tools?hours=24": { status: 200, body: { ...VIEW, usage: null } },
    });
    renderApp(<App />, "/tools");
    expect(await screen.findByText("Usage needs a database")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Tools" })).toBeInTheDocument();
  });

  it("shows a failure to load", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tools?hours=24": {
        status: 500,
        body: { error: { code: "internal", message: "Broke." } },
      },
    });
    renderApp(<App />, "/tools");
    expect(await screen.findByRole("alert")).toHaveTextContent("Broke.");
  });
});
