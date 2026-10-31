import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { mockApi, renderApp } from "../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };
const SYSTEM = {
  status: 200,
  body: { version: "0.1.0", python: "3.13", platform: "linux", memory_total_bytes: null },
};

const note = (over: Record<string, unknown>) => ({
  id: "n1",
  owner: "admin",
  content: "Prefers short answers",
  status: "approved",
  created_by: "admin",
  source_task_id: null,
  source_conversation_id: null,
  approved_at: null,
  created_at: "2026-10-31T10:00:00Z",
  updated_at: "2026-10-31T10:00:00Z",
  ...over,
});

afterEach(() => vi.restoreAllMocks());

describe("What SEED knows about you", () => {
  it("shows proposals waiting for approval and approves one", async () => {
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/memory": {
        status: 200,
        body: [
          note({
            id: "p1",
            content: "Rides a Brompton",
            status: "proposed",
            created_by: "agent",
            source_conversation_id: "c9",
          }),
          note({}),
        ],
      },
      "PATCH /api/v1/memory/p1": { status: 200, body: note({ id: "p1", content: "x" }) },
      "POST /api/v1/memory": { status: 201, body: note({ id: "n2" }) },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/settings");

    const waiting = await screen.findByRole("region", { name: "Waiting for you" });
    expect(within(waiting).getByText("Rides a Brompton")).toBeInTheDocument();
    expect(within(waiting).getByText(/Proposed by SEED/)).toBeInTheDocument();
    expect(within(waiting).getByRole("link", { name: "its chat" })).toHaveAttribute(
      "href",
      "/chat/c9",
    );
    expect(
      within(screen.getByRole("list", { name: "Remembered" })).getByText("Prefers short answers"),
    ).toBeInTheDocument();

    await user.click(within(waiting).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(spy.mock.calls.some((c) => c[1]?.method === "PATCH")).toBe(true));
    const patch = spy.mock.calls.find((c) => c[1]?.method === "PATCH");
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ approve: true });

    await user.type(screen.getByLabelText("New note"), "  Works   nights ");
    await user.click(screen.getByRole("button", { name: /Add/ }));
    await waitFor(() => expect(spy.mock.calls.some((c) => c[1]?.method === "POST")).toBe(true));
    const post = spy.mock.calls.find((c) => c[1]?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ content: "Works nights" });
  });
});

describe("Import from Hermes Agent", () => {
  it("previews a memory file, then imports what it would add", async () => {
    const plan = {
      added: ["Name: Stephen"],
      skipped: [{ content: "Prefers short answers", reason: "duplicate" }],
    };
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/memory": { status: 200, body: [note({})] },
      "POST /api/v1/memory/import?preview=true": { status: 200, body: plan },
      "POST /api/v1/memory/import": { status: 200, body: plan },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/settings");

    const file = new File(["Name: Stephen\n§\nPrefers short answers"], "USER.md");
    const input = (await screen.findByText("Or choose a file")).querySelector("input");
    await user.upload(input as HTMLInputElement, file);
    expect(screen.getByLabelText("Hermes memory file")).toHaveValue(
      "Name: Stephen\n§\nPrefers short answers",
    );
    await user.click(screen.getByRole("button", { name: "Preview" }));
    const preview = await screen.findByRole("region", { name: "Import preview" });
    expect(within(preview).getByText("Name: Stephen")).toBeInTheDocument();
    expect(
      within(preview).getByText("Skipped, already a note: Prefers short answers"),
    ).toBeInTheDocument();
    expect(spy.mock.calls.filter((c) => String(c[0]) === "/api/v1/memory/import")).toHaveLength(0);

    await user.click(within(preview).getByRole("button", { name: "Import 1 note" }));
    expect(await screen.findByText("Added 1 note.")).toBeInTheDocument();
    const saved = spy.mock.calls.find((c) => String(c[0]) === "/api/v1/memory/import");
    expect(JSON.parse(String(saved?.[1]?.body))).toEqual({
      text: "Name: Stephen\n§\nPrefers short answers",
    });
  });
});
