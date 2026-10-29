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
};

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
      "GET /api/v1/artifacts?limit=500&project_id=p2": { status: 200, body: [] },
    });
    const user = userEvent.setup();
    const { container } = renderApp(<App />, "/projects");
    const row = await screen.findByRole("link", { name: /Launch site/ });
    expect(row).toHaveAttribute("href", "/projects/p1");
    expect(row).toHaveTextContent("instructions");
    expect(row).toHaveTextContent("1 chat");
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
});
