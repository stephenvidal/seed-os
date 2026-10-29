import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { App } from "../App";
import { mockApi, renderApp } from "../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };
const MODELS = {
  status: 200,
  body: {
    provider: "ollama",
    default_model: "m-default",
    models: [{ id: "m-default", provider: "ollama", size_bytes: null }],
  },
};

const project = (over: Record<string, unknown> = {}) => ({
  id: "p1",
  owner: "admin",
  name: "Launch site",
  instructions: "Answer in French.",
  created_at: "2026-10-29T10:00:00Z",
  updated_at: "2026-10-29T10:00:00Z",
  conversations: 1,
  proposed_memories: 0,
  documents: 0,
  tasks: 1,
  ...over,
});

const conversation = {
  id: "c1",
  owner: "admin",
  title: "Hero copy",
  model: "m-default",
  project_id: "p1",
  created_at: "2026-10-29T10:00:00Z",
  updated_at: "2026-10-29T10:00:00Z",
};

const turn = {
  id: "t1",
  title: "Hero copy",
  model: "m-default",
  prompt: "Write the hero copy",
  state: "completed",
  attempt: 1,
  max_attempts: 3,
  cancel_requested: false,
  termination: "completed",
  error: null,
  result_text: "Done.",
  usage: { input_tokens: 3, output_tokens: 1 },
  last_seq: 4,
  resumable_from_step: null,
  created_at: "2026-10-29T10:00:00Z",
  updated_at: "2026-10-29T10:00:00Z",
  started_at: "2026-10-29T10:00:00Z",
  finished_at: "2026-10-29T10:00:01Z",
  conversation_id: "c1",
  turn: 1,
  versions: ["t1"],
};

const file = {
  id: "a1",
  path: "index.html",
  media_type: "text/html; charset=utf-8",
  conversation_id: "c1",
  source_title: "Hero copy",
  task_id: null,
  versions: 1,
  latest: { version: 1, task_id: "t1", size: 300, deleted: false, created_at: "" },
  created_at: "2026-10-29T10:00:00Z",
  updated_at: "2026-10-29T10:00:00Z",
};

const sent = (spy: ReturnType<typeof mockApi>, method: string, url: string) => {
  const call = spy.mock.calls.find((c) => c[1]?.method === method && String(c[0]) === url);
  return call && (JSON.parse(String(call[1]?.body)) as unknown);
};

const PROJECT_ROUTES = {
  "GET /api/v1/auth/me": ME,
  "GET /api/v1/conversations?limit=200&project_id=p1": {
    status: 200,
    body: [{ ...conversation, turns: 3, last_state: "completed" }],
  },
  "GET /api/v1/artifacts?limit=500&project_id=p1": { status: 200, body: [file] },
  "GET /api/v1/projects/p1/memories": { status: 200, body: [] },
  "GET /api/v1/projects/p1/documents": { status: 200, body: [] },
  "GET /api/v1/tasks?limit=100&project_id=p1": {
    status: 200,
    body: [{ ...turn, id: "t9", title: "Audit links", conversation_id: null, turn: null }],
  },
};

const note = (over: Record<string, unknown> = {}) => ({
  id: "m1",
  project_id: "p1",
  content: "The site uses plain CSS.",
  status: "approved",
  created_by: "admin",
  source_task_id: null,
  source_conversation_id: null,
  approved_by: "admin",
  approved_at: "2026-10-29T10:00:00Z",
  created_at: "2026-10-29T10:00:00Z",
  updated_at: "2026-10-29T10:00:00Z",
  ...over,
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Projects", () => {
  it("lists projects and creates one", async () => {
    let list = [project()];
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/projects": () => ({ status: 200, body: list }),
      "POST /api/v1/projects": () => {
        list = [project({ id: "p2", name: "Taxes", instructions: "", conversations: 0 }), ...list];
        return { status: 201, body: list[0] };
      },
      "GET /api/v1/projects/p2": () => ({ status: 200, body: list[0] }),
      "GET /api/v1/conversations?limit=200&project_id=p2": { status: 200, body: [] },
      "GET /api/v1/projects/p2/memories": { status: 200, body: [] },
      "GET /api/v1/projects/p2/documents": { status: 200, body: [] },
      "GET /api/v1/artifacts?limit=500&project_id=p2": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    const { container } = renderApp(<App />, "/projects");
    const row = await screen.findByRole("link", { name: /Launch site/ });
    expect(row).toHaveAttribute("href", "/projects/p1");
    expect(row).toHaveTextContent("instructions");
    expect(row).toHaveTextContent("1 chat");
    expect(row).not.toHaveTextContent("to review");
    expect(await axe(container)).toHaveNoViolations();

    const create = screen.getByRole("button", { name: "Create" });
    expect(create).toBeDisabled();
    await user.type(screen.getByLabelText("New project name"), "  Taxes {Enter}");
    expect(sent(spy, "POST", "/api/v1/projects")).toEqual({ name: "Taxes" });
    expect(await screen.findByRole("heading", { name: "Taxes" })).toBeInTheDocument();
    expect(await screen.findByText(/No chats yet/)).toBeInTheDocument();
    expect(await screen.findByText(/No saved files yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New chat" })).toHaveAttribute(
      "href",
      "/chat?project=p2",
    );
  });

  it("says plainly when there are no projects", async () => {
    mockApi({ "GET /api/v1/auth/me": ME, "GET /api/v1/projects": { status: 200, body: [] } });
    renderApp(<App />, "/projects");
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
  });

  it("shows a project's chats and files, and saves its instructions", async () => {
    let current = project();
    const spy = mockApi({
      ...PROJECT_ROUTES,
      "GET /api/v1/projects/p1": () => ({ status: 200, body: current }),
      "GET /api/v1/projects": () => ({ status: 200, body: [current] }),
      "PATCH /api/v1/projects/p1": () => {
        current = project({ instructions: "Be brief." });
        return { status: 200, body: current };
      },
    });
    const user = userEvent.setup();
    const { container } = renderApp(<App />, "/projects/p1");
    const chats = await screen.findByRole("region", { name: "Chats" });
    const chat = await within(chats).findByRole("link", { name: /Hero copy/ });
    expect(chat).toHaveAttribute("href", "/chat/c1");
    expect(chat).toHaveTextContent("3 messages");
    const tasks = screen.getByRole("region", { name: "Tasks" });
    expect(await within(tasks).findByRole("link", { name: /Audit links/ })).toHaveAttribute(
      "href",
      "/tasks/t9",
    );
    expect(within(tasks).getByRole("link", { name: "New task" })).toHaveAttribute(
      "href",
      "/tasks?project=p1",
    );
    const files = screen.getByRole("region", { name: "Files" });
    expect(await within(files).findByRole("link", { name: /index\.html/ })).toHaveAttribute(
      "href",
      "/studio/a1",
    );
    expect(await axe(container)).toHaveNoViolations();

    const box = screen.getByLabelText("Project instructions");
    expect(box).toHaveValue("Answer in French.");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // nothing changed yet
    await user.clear(box);
    await user.type(box, "Be brief.  ");
    await user.click(save);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(sent(spy, "PATCH", "/api/v1/projects/p1")).toEqual({ instructions: "Be brief.  " });
    expect(box).toHaveValue("Be brief.");
    expect(save).toBeDisabled();
  });

  it("deletes a project only after a confirm that says its chats are kept", async () => {
    const spy = mockApi({
      ...PROJECT_ROUTES,
      "GET /api/v1/projects/p1": { status: 200, body: project({ conversations: 2 }) },
      "DELETE /api/v1/projects/p1": { status: 204 },
      "GET /api/v1/projects": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/projects/p1");
    await user.click(await screen.findByRole("button", { name: "Delete project" }));
    const confirm = screen.getByRole("alertdialog", { name: "Delete project" });
    expect(confirm).toHaveTextContent("Its 2 chats are kept and leave the project");
    expect(spy.mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(false);
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
  });

  it("says when a project does not exist", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/projects/nope": {
        status: 404,
        body: { error: { code: "not_found", message: "No such project." } },
      },
    });
    renderApp(<App />, "/projects/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("No such project.");
  });

  it("shows how many memory proposals wait", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/projects": { status: 200, body: [project({ proposed_memories: 2 })] },
    });
    renderApp(<App />, "/projects");
    expect(await screen.findByRole("link", { name: /Launch site/ })).toHaveTextContent(
      "2 to review",
    );
  });

  it("approves, edits and rejects proposals, and adds and deletes notes", async () => {
    let notes = [
      note({
        id: "m2",
        content: "Deploys go out on Fridays.",
        status: "proposed",
        created_by: "agent",
        source_conversation_id: "c1",
        approved_by: null,
        approved_at: null,
      }),
      note({
        id: "m3",
        content: "Use metric units.",
        status: "proposed",
        created_by: "agent",
        approved_by: null,
        approved_at: null,
      }),
      note(),
    ];
    const set = (id: string, over: Record<string, unknown>) => {
      notes = notes.map((n) => (n.id === id ? { ...n, ...over } : n));
      return { status: 200, body: notes.find((n) => n.id === id) };
    };
    const spy = mockApi({
      ...PROJECT_ROUTES,
      "GET /api/v1/projects/p1": { status: 200, body: project({ proposed_memories: 2 }) },
      "GET /api/v1/projects": { status: 200, body: [project()] },
      "GET /api/v1/projects/p1/memories": () => ({ status: 200, body: notes }),
      "PATCH /api/v1/projects/p1/memories/m2": () => set("m2", { status: "approved" }),
      "PATCH /api/v1/projects/p1/memories/m3": () =>
        set("m3", { status: "approved", content: "Use metric units only." }),
      "DELETE /api/v1/projects/p1/memories/m1": () => {
        notes = notes.filter((n) => n.id !== "m1");
        return { status: 204 };
      },
      "POST /api/v1/projects/p1/memories": () => {
        notes = [...notes, note({ id: "m4", content: "Stephen likes short answers." })];
        return { status: 201, body: notes.at(-1) };
      },
    });
    const user = userEvent.setup();
    const { container } = renderApp(<App />, "/projects/p1");
    const waiting = await screen.findByRole("region", { name: "Waiting for you" });
    expect(within(waiting).getAllByRole("listitem")).toHaveLength(2);
    const first = within(waiting).getAllByRole("listitem")[0]!;
    expect(first).toHaveTextContent("Deploys go out on Fridays.");
    expect(first).toHaveTextContent("Proposed by SEED in its chat");
    expect(within(first).getByRole("link", { name: "its chat" })).toHaveAttribute(
      "href",
      "/chat/c1",
    );
    const remembered = screen.getByRole("list", { name: "Remembered" });
    expect(remembered).toHaveTextContent("The site uses plain CSS.");
    expect(remembered).toHaveTextContent("Added by admin");
    expect(within(remembered).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();

    await user.click(within(first).getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(screen.getByRole("list", { name: "Remembered" })).toHaveTextContent(
        "Deploys go out on Fridays.",
      ),
    );
    expect(sent(spy, "PATCH", "/api/v1/projects/p1/memories/m2")).toEqual({ approve: true });

    const second = within(screen.getByRole("region", { name: "Waiting for you" })).getByRole(
      "listitem",
    );
    await user.click(within(second).getByRole("button", { name: "Edit" }));
    const box = within(second).getByLabelText("Note");
    await user.clear(box);
    await user.type(box, "Use metric  units only.");
    await user.click(within(second).getByRole("button", { name: "Save and approve" }));
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Waiting for you" })).not.toBeInTheDocument(),
    );
    expect(sent(spy, "PATCH", "/api/v1/projects/p1/memories/m3")).toEqual({
      content: "Use metric units only.",
      approve: true,
    });

    const css = within(screen.getByRole("list", { name: "Remembered" }))
      .getAllByRole("listitem")
      .find((li) => li.textContent?.includes("plain CSS"))!;
    await user.click(within(css).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(screen.getByRole("list", { name: "Remembered" })).not.toHaveTextContent("plain CSS"),
    );

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    await user.type(screen.getByLabelText("New note"), " Stephen  likes short answers. {Enter}");
    expect(sent(spy, "POST", "/api/v1/projects/p1/memories")).toEqual({
      content: "Stephen likes short answers.",
    });
    expect(
      await within(screen.getByRole("list", { name: "Remembered" })).findByText(
        "Stephen likes short answers.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("New note")).toHaveValue("");
  });

  it("rejects a proposal", async () => {
    let notes = [note({ id: "m2", status: "proposed", created_by: "agent", content: "A guess." })];
    const spy = mockApi({
      ...PROJECT_ROUTES,
      "GET /api/v1/projects/p1": { status: 200, body: project({ proposed_memories: 1 }) },
      "GET /api/v1/projects": { status: 200, body: [project()] },
      "GET /api/v1/projects/p1/memories": () => ({ status: 200, body: notes }),
      "DELETE /api/v1/projects/p1/memories/m2": () => {
        notes = [];
        return { status: 204 };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/projects/p1");
    const waiting = await screen.findByRole("region", { name: "Waiting for you" });
    await user.click(within(waiting).getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("Nothing remembered yet.")).toBeInTheDocument();
    expect(spy.mock.calls.some((c) => c[1]?.method === "PATCH")).toBe(false);
  });

  it("adds text documents to the project's knowledge and deletes them", async () => {
    const doc = (id: string, name: string, chars: number, chunks: number) => ({
      id,
      project_id: "p1",
      name,
      chars,
      chunks,
      created_by: "admin",
      created_at: "2026-10-29T10:00:00Z",
    });
    let docs = [doc("d1", "guide.md", 12345, 9)];
    const spy = mockApi({
      ...PROJECT_ROUTES,
      "GET /api/v1/projects/p1": { status: 200, body: project({ documents: 1 }) },
      "GET /api/v1/projects": { status: 200, body: [project()] },
      "GET /api/v1/projects/p1/documents": () => ({ status: 200, body: docs }),
      "POST /api/v1/projects/p1/documents": () => {
        const body = JSON.parse(
          String(spy.mock.calls.filter((c) => c[1]?.method === "POST").at(-1)?.[1]?.body),
        ) as { name: string; content: string };
        if (body.name === "guide.md")
          return {
            status: 409,
            body: {
              error: {
                code: "name_taken",
                message: "This project already has a document with that name.",
              },
            },
          };
        docs = [...docs, doc("d2", body.name, body.content.length, 1)];
        return { status: 201, body: docs.at(-1) };
      },
      "DELETE /api/v1/projects/p1/documents/d1": () => {
        docs = docs.filter((d) => d.id !== "d1");
        return { status: 204 };
      },
    });
    const user = userEvent.setup();
    const { container } = renderApp(<App />, "/projects/p1");
    const list = await screen.findByRole("list", { name: "Documents" });
    expect(list).toHaveTextContent("guide.md");
    expect(list).toHaveTextContent("12,345 characters · 9 passages");
    expect(await axe(container)).toHaveNoViolations();

    const input = screen.getByLabelText("Add documents");
    await user.upload(input, new File(["Water twice a week."], "care.txt", { type: "text/plain" }));
    expect(await within(list).findByText("care.txt")).toBeInTheDocument();
    expect(sent(spy, "POST", "/api/v1/projects/p1/documents")).toEqual({
      name: "care.txt",
      content: "Water twice a week.",
    });

    await user.upload(input, new File(["again"], "guide.md", { type: "text/markdown" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This project already has a document with that name.",
    );

    const posts = () => spy.mock.calls.filter((c) => c[1]?.method === "POST").length;
    const before = posts();
    await user.upload(input, new File(["x".repeat(256 * 1024 + 1)], "huge.txt"));
    expect(await screen.findByRole("alert")).toHaveTextContent("huge.txt is too long");
    expect(posts()).toBe(before); // never sent

    await user.click(within(list).getByRole("button", { name: "Delete guide.md" }));
    await waitFor(() => expect(list).not.toHaveTextContent("guide.md"));
  });
});

describe("Chat in a project", () => {
  it("starts a chat in the project it was opened from", async () => {
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [] },
      "GET /api/v1/projects/p1": { status: 200, body: project() },
      "GET /api/v1/projects": { status: 200, body: [project()] },
      "POST /api/v1/conversations": {
        status: 201,
        body: { conversation, turns: [turn] },
      },
      "GET /api/v1/conversations/c1": { status: 200, body: { conversation, turns: [turn] } },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/chat?project=p1");
    expect(await screen.findByRole("link", { name: "Launch site" })).toHaveAttribute(
      "href",
      "/projects/p1",
    );
    await screen.findByRole("option", { name: "m-default" });
    await user.type(screen.getByLabelText("Message"), "Write the hero copy{Enter}");
    await waitFor(() =>
      expect(sent(spy, "POST", "/api/v1/conversations")).toEqual({
        model: "m-default",
        prompt: "Write the hero copy",
        project_id: "p1",
      }),
    );
    expect(await screen.findByLabelText("Project")).toHaveValue("p1");
  });

  it("moves a chat into a project and out again", async () => {
    let current = { ...conversation, project_id: null as string | null };
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": {
        status: 200,
        body: [{ ...conversation, turns: 1, last_state: "completed" }],
      },
      "GET /api/v1/projects": { status: 200, body: [project()] },
      "GET /api/v1/conversations/c1": () => ({
        status: 200,
        body: { conversation: current, turns: [turn] },
      }),
      "PUT /api/v1/conversations/c1/project": () => {
        const call = spy.mock.calls.filter((c) => c[1]?.method === "PUT").at(-1);
        const body = JSON.parse(String(call?.[1]?.body)) as { project_id: string | null };
        current = { ...conversation, project_id: body.project_id };
        return { status: 200, body: current };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/chat/c1");
    const select = await screen.findByLabelText("Project");
    expect(select).toHaveValue("");
    expect(screen.queryByRole("link", { name: "Open project" })).not.toBeInTheDocument();

    await user.selectOptions(select, "Launch site");
    expect(await screen.findByRole("link", { name: "Open project" })).toHaveAttribute(
      "href",
      "/projects/p1",
    );
    expect(select).toHaveValue("p1");
    await user.selectOptions(select, "None");
    await waitFor(() => expect(select).toHaveValue(""));
    const puts = spy.mock.calls.filter((c) => c[1]?.method === "PUT").map((c) => c[1]?.body);
    expect(puts).toEqual([
      JSON.stringify({ project_id: "p1" }),
      JSON.stringify({ project_id: null }),
    ]);
  });

  it("points to memory waiting for review", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/conversations?limit=200": { status: 200, body: [] },
      "GET /api/v1/projects": { status: 200, body: [project({ proposed_memories: 1 })] },
      "GET /api/v1/conversations/c1": { status: 200, body: { conversation, turns: [turn] } },
    });
    renderApp(<App />, "/chat/c1");
    expect(await screen.findByRole("link", { name: "Memory to review" })).toHaveAttribute(
      "href",
      "/projects/p1",
    );
  });
});
