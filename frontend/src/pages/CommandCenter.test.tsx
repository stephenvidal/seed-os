import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { App } from "../App";
import { mockApi, renderApp } from "../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };
const SYSTEM = {
  status: 200,
  body: {
    version: "0.1.0",
    python: "3.13.0",
    platform: "Linux",
    uptime_seconds: 125,
    cpu_count: 4,
    load_average: [0.5, 0.4, 0.3],
    memory_total_bytes: 16 * 1024 ** 3,
    memory_available_bytes: 12 * 1024 ** 3,
    process_rss_bytes: 50 * 1024 ** 2,
  },
};
const NOW = "2026-10-29T12:00:00Z";

const task = (over: Record<string, unknown>) => ({
  id: "t",
  title: "A task",
  model: "m-a",
  prompt: "p",
  state: "completed",
  attempt: 1,
  max_attempts: 3,
  cancel_requested: false,
  termination: null,
  error: null,
  result_text: null,
  usage: { input_tokens: 0, output_tokens: 0 },
  last_seq: 1,
  resumable_from_step: null,
  created_at: "2026-10-29T11:00:00Z",
  updated_at: "2026-10-29T11:00:00Z",
  started_at: null,
  finished_at: null,
  conversation_id: null,
  turn: null,
  awaiting_approval: null,
  ...over,
});

const EMPTY = {
  window_hours: 24,
  generated_at: NOW,
  counts: { queued: 0, running: 0, waiting: 0, completed: 0, failed: 0, canceled: 0 },
  attention: [],
  active: [],
  recent: [],
  usage: [],
};

afterEach(() => vi.restoreAllMocks());

describe("Command Center", () => {
  it("shows what needs attention, what is running, recent work and token use", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/overview?hours=24": {
        status: 200,
        body: {
          ...EMPTY,
          counts: { queued: 1, running: 1, waiting: 1, completed: 1234, failed: 1, canceled: 0 },
          attention: [
            task({
              id: "w",
              title: "Build the site",
              state: "waiting",
              conversation_id: "c9",
              turn: 1,
              awaiting_approval: { id: "c", name: "run_command", arguments: {} },
            }),
            task({ id: "f", title: "Broken job", state: "failed", error: "auth: Unauthorized" }),
          ],
          active: [
            task({
              id: "r",
              title: "Long job",
              state: "running",
              started_at: "2026-10-29T11:55:00Z",
            }),
            task({ id: "q", title: "Next job", state: "queued" }),
          ],
          recent: [
            task({
              id: "d",
              title: "Done job",
              usage: { input_tokens: 1200, output_tokens: 300 },
              finished_at: "2026-10-29T10:00:00Z",
            }),
          ],
          usage: [{ model: "m-a", tasks: 3, input_tokens: 12000, output_tokens: 3400 }],
        },
      },
    });
    const { container } = renderApp(<App />);

    const attention = await screen.findByRole("region", { name: "Needs attention" });
    expect(within(attention).getByText("2")).toBeInTheDocument();
    const approve = within(attention).getByRole("link", { name: /Build the site/ });
    expect(approve).toHaveAttribute("href", "/chat/c9"); // a chat turn opens its chat
    expect(approve).toHaveTextContent("Wants to run run_command");
    expect(approve).toHaveTextContent("needs you");
    const broken = within(attention).getByRole("link", { name: /Broken job/ });
    expect(broken).toHaveAttribute("href", "/tasks/f");
    expect(broken).toHaveTextContent("auth: Unauthorized");

    const active = screen.getByRole("region", { name: "In progress" });
    const rows = within(active).getAllByRole("link");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Long job"),
      expect.stringContaining("Next job"),
    ]);
    expect(rows[0]).toHaveTextContent("started 5m ago");

    const recent = screen.getByRole("region", { name: "Recently completed" });
    expect(within(recent).getByRole("link", { name: /Done job/ })).toHaveTextContent(
      "1,500 tokens · 2h ago",
    );

    const stats = screen.getByText("Completed (24h)").closest("div");
    expect(stats).toHaveTextContent("1,234");
    const usage = screen.getByRole("region", { name: "Model usage (24h)" });
    expect(within(usage).getByRole("row", { name: /m-a/ })).toHaveTextContent("m-a312,0003,400");
    expect(usage).toHaveTextContent("Spend is not shown: no model prices are configured.");
    expect(await axe(container)).toHaveNoViolations();
  });

  it("says plainly when there is nothing yet", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/overview?hours=24": { status: 200, body: EMPTY },
    });
    renderApp(<App />);
    expect(await screen.findByText("Nothing waiting on you")).toBeInTheDocument();
    expect(screen.getByText("No active work")).toBeInTheDocument();
    expect(screen.getByText("No completed work yet")).toBeInTheDocument();
    expect(screen.getByText("No model use yet")).toBeInTheDocument();
    expect(screen.queryByText(/Arrives in/)).toBeNull(); // built now: no milestone note
  });

  it("explains when there is no database", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/overview?hours=24": {
        status: 503,
        body: {
          error: {
            code: "database_not_configured",
            message: "Tasks need a database. Set SEED_DATABASE_URL.",
          },
        },
      },
    });
    renderApp(<App />);
    expect(await screen.findByText("Tasks need a database")).toBeInTheDocument();
    expect(screen.getByText("System health")).toBeInTheDocument(); // the rest still works
  });
});
