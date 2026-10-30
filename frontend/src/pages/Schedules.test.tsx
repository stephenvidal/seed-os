import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { App } from "../App";
import { describeTimetable } from "../lib/schedules";
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
const PROJECTS = {
  status: 200,
  body: [
    {
      id: "p1",
      owner: "admin",
      name: "Research",
      instructions: "",
      created_at: "2026-10-29T10:00:00Z",
      updated_at: "2026-10-29T10:00:00Z",
      conversations: 0,
      proposed_memories: 0,
      documents: 0,
    },
  ],
};

const schedule = (over: Record<string, unknown> = {}) => ({
  id: "s1",
  owner: "admin",
  name: "Hourly check",
  prompt: "Check the logs.",
  model: "m-default",
  project_id: null,
  kind: "interval",
  every_minutes: 120,
  at_time: null,
  timezone: "UTC",
  enabled: true,
  next_run_at: "2026-10-30T12:00:00Z",
  last_run_at: null,
  last_outcome: null,
  last_task_id: null,
  created_at: "2026-10-29T10:00:00Z",
  updated_at: "2026-10-29T10:00:00Z",
  ...over,
});

const sent = (spy: ReturnType<typeof mockApi>, method: string, url: string) => {
  const call = spy.mock.calls.find((c) => c[1]?.method === method && String(c[0]) === url);
  return call && (JSON.parse(String(call[1]?.body)) as unknown);
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("describeTimetable", () => {
  it("puts a timetable in words", () => {
    const i = (m: number) =>
      describeTimetable({ kind: "interval", every_minutes: m, at_time: null, timezone: "UTC" });
    expect([i(5), i(60), i(120), i(90), i(1440), i(2880)]).toEqual([
      "Every 5 minutes",
      "Every hour",
      "Every 2 hours",
      "Every 90 minutes",
      "Every day",
      "Every 2 days",
    ]);
    expect(
      describeTimetable({
        kind: "daily",
        every_minutes: null,
        at_time: "09:30:00",
        timezone: "Europe/Paris",
      }),
    ).toBe("Daily at 09:30 (Europe/Paris)");
  });
});

describe("Schedules", () => {
  it("lists schedules with their timetable, last run and project", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/projects": PROJECTS,
      "GET /api/v1/schedules": {
        status: 200,
        body: [
          schedule({
            project_id: "p1",
            last_run_at: "2026-10-30T10:00:00Z",
            last_outcome: "skipped_busy",
            last_task_id: "t9",
          }),
          schedule({
            id: "s2",
            name: "Morning",
            kind: "daily",
            every_minutes: null,
            at_time: "09:30:00",
            timezone: "Europe/Paris",
            enabled: false,
            next_run_at: null,
          }),
        ],
      },
    });
    const { container } = renderApp(<App />, "/schedules");
    const list = await screen.findByRole("list", { name: "Schedules" });
    const [hourly, morning] = within(list).getAllByRole("listitem");
    expect(hourly).toHaveTextContent("Every 2 hours");
    expect(hourly).toHaveTextContent("Research");
    expect(hourly).toHaveTextContent("skipped: the last task was still going");
    expect(within(hourly!).getByRole("link", { name: "Last task" })).toHaveAttribute(
      "href",
      "/tasks/t9",
    );
    expect(morning).toHaveTextContent("Daily at 09:30 (Europe/Paris)");
    expect(morning).toHaveTextContent("paused");
    expect(morning).toHaveTextContent("Has not run yet");
    expect(await axe(container)).toHaveNoViolations();
  });

  it("creates a daily schedule in the chosen time zone, and shows a refusal", async () => {
    let schedules: unknown[] = [];
    let refuse = true;
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/projects": PROJECTS,
      "GET /api/v1/schedules": () => ({ status: 200, body: schedules }),
      "POST /api/v1/schedules": () => {
        if (refuse) {
          refuse = false;
          return {
            status: 422,
            body: { error: { code: "invalid_request", message: "Unknown time zone." } },
          };
        }
        schedules = [schedule({ name: "Morning", kind: "daily" })];
        return { status: 201, body: schedules[0] };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/schedules");
    expect(await screen.findByText("No schedules yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New schedule" }));
    const form = screen.getByRole("group", { name: "New schedule" });
    const create = within(form).getByRole("button", { name: "Create" });
    expect(create).toBeDisabled(); // a name and a prompt are needed
    await user.type(within(form).getByLabelText("Name"), "  Morning  ");
    await user.type(within(form).getByLabelText("What the task should do"), "Summarise.");
    await within(form).findByRole("option", { name: "m-small" });
    await user.selectOptions(within(form).getByLabelText("Project"), "Research");
    await user.click(within(form).getByLabelText("Daily at a time"));
    const tz = within(form).getByLabelText("Time zone");
    await user.clear(tz);
    await user.type(tz, "Nowhere/Land");
    await user.click(create);
    expect(await within(form).findByRole("alert")).toHaveTextContent("Unknown time zone.");
    // The default model is the provider's, the time starts at 09:00, and an interval is not sent.
    expect(sent(spy, "POST", "/api/v1/schedules")).toEqual({
      name: "Morning",
      prompt: "Summarise.",
      model: "m-default",
      project_id: "p1",
      kind: "daily",
      every_minutes: null,
      at_time: "09:00",
      timezone: "Nowhere/Land",
      enabled: true,
    });
    await user.clear(tz);
    await user.type(tz, "Europe/Paris");
    await user.click(create);
    await waitFor(() => expect(screen.queryByRole("group", { name: "New schedule" })).toBeNull());
    expect(await screen.findByText("Morning")).toBeInTheDocument();
  });

  it("will not create an interval outside 5 to 10080 minutes", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/projects": PROJECTS,
      "GET /api/v1/schedules": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/schedules");
    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const form = screen.getByRole("group", { name: "New schedule" });
    await user.type(within(form).getByLabelText("Name"), "x");
    await user.type(within(form).getByLabelText("What the task should do"), "y");
    await within(form).findByRole("option", { name: "m-small" });
    const minutes = within(form).getByLabelText(/Minutes between runs/);
    const create = within(form).getByRole("button", { name: "Create" });
    for (const [value, ok] of [
      ["4", false],
      ["5", true],
      ["10080", true],
      ["10081", false],
    ] as const) {
      await user.clear(minutes);
      await user.type(minutes, value);
      if (ok) expect(create).toBeEnabled();
      else expect(create).toBeDisabled();
    }
  });

  it("pauses, runs now, edits as a whole and deletes only after a confirm", async () => {
    let schedules = [schedule()];
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/projects": PROJECTS,
      "GET /api/v1/schedules": () => ({ status: 200, body: schedules }),
      "PUT /api/v1/schedules/s1": () => {
        // The server keeps what it was sent.
        const puts = spy.mock.calls.filter((c) => c[1]?.method === "PUT");
        const body = JSON.parse(String(puts[puts.length - 1]?.[1]?.body)) as Record<
          string,
          unknown
        >;
        schedules = [schedule(body)];
        return { status: 200, body: schedules[0] };
      },
      "POST /api/v1/schedules/s1/run": { status: 200, body: { task_id: "t1" } },
      "DELETE /api/v1/schedules/s1": () => {
        schedules = [];
        return { status: 204 };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/schedules");
    await user.click(await screen.findByRole("button", { name: "Run Hourly check now" }));
    expect(await screen.findByRole("link", { name: "Open it" })).toHaveAttribute(
      "href",
      "/tasks/t1",
    );

    await user.click(screen.getByRole("button", { name: "Pause Hourly check" }));
    expect(await screen.findByRole("button", { name: "Resume Hourly check" })).toBeInTheDocument();
    expect(sent(spy, "PUT", "/api/v1/schedules/s1")).toMatchObject({
      enabled: false,
      every_minutes: 120,
      prompt: "Check the logs.",
    });

    await user.click(screen.getByRole("button", { name: "Edit Hourly check" }));
    const form = screen.getByRole("listitem", { name: "Edit Hourly check" });
    const minutes = within(form).getByLabelText(/Minutes between runs/);
    await user.clear(minutes);
    await user.type(minutes, "30");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Every 30 minutes")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete Hourly check" }));
    const confirm = screen.getByRole("group", { name: "Delete Hourly check?" });
    await user.click(within(confirm).getByRole("button", { name: "Keep" }));
    expect(spy.mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Delete Hourly check" }));
    await user.click(
      within(screen.getByRole("group", { name: "Delete Hourly check?" })).getByRole("button", {
        name: "Delete",
      }),
    );
    expect(await screen.findByText("No schedules yet")).toBeInTheDocument();
  });
});
