import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { App } from "../App";
import { mockApi, renderApp } from "../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };
const TOOLS = {
  status: 200,
  body: { tools: [], usage: [], window_hours: 24, usage_available: true },
};
const CODER = {
  id: "a1",
  owner: "admin",
  name: "Coder",
  description: "Writes code.",
  instructions: "",
  model: null,
  tools: [],
  skills: [],
  created_at: "2026-10-29T10:00:00Z",
  updated_at: "2026-10-29T10:00:00Z",
};

const skill = (over: Record<string, unknown> = {}) => ({
  id: "s1",
  owner: "admin",
  agent_id: null,
  name: "deploy-site",
  description: "Ship the site to the VPS.",
  tags: ["ops"],
  body: "1. Build.\n2. Push.",
  written_by_task: null,
  created_at: "2026-10-30T10:00:00Z",
  updated_at: "2026-10-30T10:00:00Z",
  ...over,
});

const sent = (spy: ReturnType<typeof mockApi>, method: string, url: string) => {
  const call = spy.mock.calls.find((c) => c[1]?.method === method && String(c[0]) === url);
  return call && (JSON.parse(String(call[1]?.body)) as unknown);
};

afterEach(() => vi.restoreAllMocks());

describe("Skills", () => {
  it("lists skills with who may use them and who wrote them", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tools?hours=24": TOOLS,
      "GET /api/v1/agents": { status: 200, body: [CODER] },
      "GET /api/v1/skills": {
        status: 200,
        body: [
          skill(),
          skill({ id: "s2", name: "tests", agent_id: "a1", tags: [], written_by_task: "t9" }),
        ],
      },
    });
    const { container } = renderApp(<App />, "/tools");
    const list = await screen.findByRole("list", { name: "Skills" });
    const [deploy, tests] = within(list).getAllByRole("listitem");
    expect(deploy).toHaveTextContent("deploy-site");
    expect(deploy).toHaveTextContent("Ship the site to the VPS.");
    expect(deploy).toHaveTextContent("shared");
    expect(deploy).toHaveTextContent("ops");
    expect(deploy).not.toHaveTextContent("written by");
    expect(deploy).not.toHaveTextContent("1. Build."); // the instructions show when editing
    expect(await within(tests!).findByText("only Coder")).toBeInTheDocument();
    expect(within(tests!).getByRole("link", { name: /written by SEED/ })).toHaveAttribute(
      "href",
      "/tasks/t9",
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it("writes a skill, checking the name first, and shows a refusal", async () => {
    let skills: unknown[] = [];
    let refuse = true;
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tools?hours=24": TOOLS,
      "GET /api/v1/agents": { status: 200, body: [CODER] },
      "GET /api/v1/skills": () => ({ status: 200, body: skills }),
      "POST /api/v1/skills": () => {
        if (refuse) {
          refuse = false;
          return {
            status: 409,
            body: { error: { code: "name_taken", message: "You already have a skill called x." } },
          };
        }
        skills = [skill({ agent_id: "a1" })];
        return { status: 201, body: skills[0] };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/tools");
    expect(await screen.findByText("No skills yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New skill" }));
    const form = screen.getByRole("group", { name: "New skill" });
    const create = within(form).getByRole("button", { name: "Create" });
    await user.type(within(form).getByLabelText("Name"), "Deploy Site");
    await user.type(within(form).getByLabelText("What it is for"), "Ship  it.");
    await user.type(within(form).getByLabelText("Instructions"), "1. Build.");
    expect(create).toBeDisabled(); // a space is not allowed in a name
    expect(within(form).getByText(/Lower-case letters/)).toHaveClass("text-danger");
    await user.clear(within(form).getByLabelText("Name"));
    await user.type(within(form).getByLabelText("Name"), "Deploy-Site");
    expect(within(form).getByText(/Start a message with \/deploy-site/)).toBeInTheDocument();
    await user.type(within(form).getByLabelText("Tags (comma separated)"), "ops, , web ");
    await within(form).findByRole("option", { name: "Only Coder" });
    await user.selectOptions(within(form).getByLabelText("Who can use it"), "a1");
    await user.click(create);

    expect(await within(form).findByRole("alert")).toHaveTextContent("already have a skill");
    expect(sent(spy, "POST", "/api/v1/skills")).toEqual({
      name: "deploy-site",
      description: "Ship it.",
      tags: ["ops", "web"],
      body: "1. Build.",
      agent_id: "a1",
    });
    await user.click(create);
    await waitFor(() => expect(screen.queryByRole("group", { name: "New skill" })).toBeNull());
    const list = await screen.findByRole("list", { name: "Skills" });
    expect(list).toHaveTextContent("deploy-site");
  });

  it("imports a pasted or uploaded SKILL.md and says what it left out", async () => {
    let fail = true;
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tools?hours=24": TOOLS,
      "GET /api/v1/agents": { status: 200, body: [] },
      "GET /api/v1/skills": { status: 200, body: [] },
      "POST /api/v1/skills/import": () => {
        if (fail) {
          fail = false;
          return {
            status: 422,
            body: {
              error: {
                code: "invalid_skill_md",
                message: "A SKILL.md starts with a YAML header between two --- lines.",
              },
            },
          };
        }
        return {
          status: 201,
          body: { skill: skill({ name: "deploy-k8s" }), ignored: ["platforms", "version"] },
        };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/tools");
    await screen.findByText("No skills yet");
    await user.click(screen.getByRole("button", { name: "Import" }));
    const form = screen.getByRole("group", { name: "Import a skill" });
    await user.type(within(form).getByLabelText("SKILL.md"), "no header");
    await user.click(within(form).getByRole("button", { name: "Import" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("starts with a YAML header");

    const text = "---\nname: deploy-k8s\ndescription: Deploy\n---\nSteps.";
    const file = new File([text], "SKILL.md", { type: "text/markdown" });
    await user.upload(within(form).getByLabelText("Or choose a file"), file);
    expect(within(form).getByLabelText("SKILL.md")).toHaveValue(text);
    await user.click(within(form).getByRole("button", { name: "Import" }));
    const done = await within(form).findByRole("status");
    expect(done).toHaveTextContent("Imported deploy-k8s.");
    expect(done).toHaveTextContent("does not use these parts of its header: platforms, version");
    const bodies = spy.mock.calls
      .filter((c) => String(c[0]) === "/api/v1/skills/import")
      .map((c) => JSON.parse(String(c[1]?.body)) as unknown);
    expect(bodies[1]).toEqual({ text, agent_id: null });
  });

  it("changes and deletes a skill", async () => {
    let skills = [skill()];
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/tools?hours=24": TOOLS,
      "GET /api/v1/agents": { status: 200, body: [CODER] },
      "GET /api/v1/skills": () => ({ status: 200, body: skills }),
      "PUT /api/v1/skills/s1": () => {
        skills = [skill({ description: "Ship carefully." })];
        return { status: 200, body: skills[0] };
      },
      "DELETE /api/v1/skills/s1": () => {
        skills = [];
        return { status: 204 };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/tools");
    await screen.findByRole("list", { name: "Skills" });
    await user.click(screen.getByRole("button", { name: "Edit deploy-site" }));
    const form = screen.getByRole("listitem", { name: "Edit deploy-site" });
    expect(within(form).getByLabelText("Instructions")).toHaveValue("1. Build.\n2. Push.");
    expect(within(form).getByLabelText("Tags (comma separated)")).toHaveValue("ops");
    const what = within(form).getByLabelText("What it is for");
    await user.clear(what);
    await user.type(what, "Ship carefully.");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Ship carefully.")).toBeInTheDocument();
    expect(sent(spy, "PUT", "/api/v1/skills/s1")).toEqual({
      name: "deploy-site",
      description: "Ship carefully.",
      tags: ["ops"],
      body: "1. Build.\n2. Push.",
      agent_id: null,
    });

    await user.click(screen.getByRole("button", { name: "Delete deploy-site" }));
    const confirm = screen.getByRole("group", { name: "Delete deploy-site?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("No skills yet")).toBeInTheDocument();
  });
});
