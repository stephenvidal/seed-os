import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { App } from "../../App";
import { notificationLink } from "../../lib/notifications";
import type { Notification } from "../../lib/notifications";
import { mockApi, renderApp } from "../../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };

const note = (over: Partial<Notification> = {}): Notification => ({
  id: "n1",
  kind: "task_failed",
  title: "Nightly backup",
  body: "Disk is full.",
  task_id: "t1",
  schedule_id: null,
  created_at: "2026-10-30T09:00:00Z",
  read_at: null,
  ...over,
});

afterEach(() => vi.restoreAllMocks());

describe("notificationLink", () => {
  it("leads to the task, or to the schedules for a skipped run", () => {
    expect(notificationLink(note())).toBe("/tasks/t1");
    expect(notificationLink(note({ kind: "schedule_skipped", schedule_id: "s1" }))).toBe(
      "/schedules",
    );
  });
});

describe("Notification bell", () => {
  it("shows the unread count, opens a notification and marks it read", async () => {
    let items = [
      note(),
      note({
        id: "n2",
        kind: "approval_needed",
        title: "Deploy",
        body: "Waiting for your approval to call run_command.",
        task_id: "t2",
      }),
      note({ id: "n3", kind: "task_completed", title: "Report", read_at: "2026-10-30T09:05:00Z" }),
    ];
    const unread = () => items.filter((n) => !n.read_at).length;
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/notifications?limit=20": () => ({
        status: 200,
        body: { unread: unread(), items },
      }),
      "POST /api/v1/notifications/n2/read": () => {
        items = items.map((n) => (n.id === "n2" ? { ...n, read_at: "2026-10-30T10:00:00Z" } : n));
        return { status: 204 };
      },
      "GET /api/v1/tasks/t2": { status: 404, body: { error: { code: "not_found", message: "x" } } },
      "GET /api/v1/tasks/t2/events?after=0": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    const { container } = renderApp(<App />, "/tools-unmocked-page");
    const bell = await screen.findByRole("button", { name: "Notifications, 2 unread" });
    await user.click(bell);
    const menu = await screen.findByRole("menu");
    const entries = within(menu).getAllByRole("menuitem");
    expect(entries.map((e) => e.textContent)).toEqual([
      "Mark all read",
      expect.stringContaining("Failed") as unknown as string,
      expect.stringContaining("Needs your approval") as unknown as string,
      expect.stringContaining("Finished") as unknown as string,
    ]);
    expect(entries[1]).toHaveTextContent("Nightly backup");
    expect(entries[1]).toHaveTextContent("Disk is full.");
    expect(entries[1]).toHaveTextContent("unread");
    expect(entries[3]).not.toHaveTextContent("unread");
    expect(await axe(container)).toHaveNoViolations();

    await user.click(within(menu).getByRole("menuitem", { name: /Deploy/ }));
    await waitFor(() =>
      expect(spy.mock.calls.some((c) => String(c[0]) === "/api/v1/notifications/n2/read")).toBe(
        true,
      ),
    );
    expect(await screen.findByRole("button", { name: "Notifications, 1 unread" })).toBeVisible();
    // It went to the task.
    expect(spy.mock.calls.some((c) => String(c[0]).startsWith("/api/v1/tasks/t2"))).toBe(true);
  });

  it("marks all read, and says what it will tell you when there is nothing", async () => {
    let items = [note()];
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/notifications?limit=20": () => ({
        status: 200,
        body: { unread: items.filter((n) => !n.read_at).length, items },
      }),
      "POST /api/v1/notifications/read-all": () => {
        items = [];
        return { status: 204 };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/nowhere");
    await user.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    await user.click(await screen.findByRole("menuitem", { name: "Mark all read" }));
    expect(await screen.findByText(/You will hear here when a task finishes/)).toBeVisible();
    await user.keyboard("{Escape}");
    expect(await screen.findByRole("button", { name: "Notifications" })).toBeVisible();
    expect(spy.mock.calls.some((c) => c[1]?.method === "POST")).toBe(true);
  });

  it("shows why the list could not load", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/notifications?limit=20": {
        status: 503,
        body: {
          error: { code: "database_not_configured", message: "Notifications need a database." },
        },
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/nowhere");
    await user.click(await screen.findByRole("button", { name: "Notifications" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Notifications need a database.");
  });
});
