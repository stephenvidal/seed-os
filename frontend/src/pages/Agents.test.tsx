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
    models: [
      { id: "m-small", provider: "ollama", size_bytes: null },
      { id: "m-default", provider: "ollama", size_bytes: null },
    ],
  },
};

const agent = (over: Record<string, unknown> = {}) => ({
  id: "a1",
  owner: "admin",
  name: "Researcher",
  description: "Reads files and reports what they say.",
  instructions: "Cite sources.",
  model: null,
  tools: ["list_files", "read_file"],
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

describe("Agents", () => {
  it("lists agents with their model and tools", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/agents": {
        status: 200,
        body: [agent(), agent({ id: "a2", name: "Coder", model: "m-small", tools: [] })],
      },
    });
    const { container } = renderApp(<App />, "/agents");
    const list = await screen.findByRole("list", { name: "Agents" });
    const [researcher, coder] = within(list).getAllByRole("listitem");
    expect(researcher).toHaveTextContent("Researcher");
    expect(researcher).toHaveTextContent("task's model");
    expect(researcher).toHaveTextContent("Read files");
    expect(coder).toHaveTextContent("m-small");
    expect(coder).toHaveTextContent("no tools");
    expect(screen.getByText(/hands it part of the job as a task of its own/)).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("creates an agent with the chosen model and tools, and shows a refusal", async () => {
    let agents = [agent()];
    let refuse = true;
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/agents": () => ({ status: 200, body: agents }),
      "POST /api/v1/agents": () => {
        if (refuse) {
          refuse = false;
          return {
            status: 409,
            body: {
              error: { code: "name_taken", message: "You already have an agent called Scout." },
            },
          };
        }
        agents = [...agents, agent({ id: "a3", name: "Scout", tools: ["run_command"] })];
        return { status: 201, body: agents[1] };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/agents");
    await screen.findByRole("list", { name: "Agents" });
    await user.click(screen.getByRole("button", { name: "New agent" }));
    const form = screen.getByRole("group", { name: "New agent" });
    const create = within(form).getByRole("button", { name: "Create" });
    expect(create).toBeDisabled(); // a name and a purpose are needed
    await user.type(within(form).getByLabelText("Name"), "  Scout ");
    await user.type(within(form).getByLabelText("What it is for"), "Looks  around.");
    await within(form).findByRole("option", { name: "m-small" });
    await user.selectOptions(within(form).getByLabelText("Model"), "m-small");
    await user.click(within(form).getByLabelText(/Run commands/));
    await user.click(create);

    expect(await within(form).findByRole("alert")).toHaveTextContent("already have an agent");
    expect(sent(spy, "POST", "/api/v1/agents")).toEqual({
      name: "Scout",
      description: "Looks around.",
      instructions: "",
      model: "m-small",
      tools: ["run_command"],
    });
    await user.click(create);
    await waitFor(() => expect(screen.queryByRole("group", { name: "New agent" })).toBeNull());
    expect(await screen.findByText("Scout")).toBeInTheDocument();
  });

  it("edits an agent as a whole, and deletes one only after a confirm", async () => {
    let agents = [agent()];
    const spy = mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/models": MODELS,
      "GET /api/v1/agents": () => ({ status: 200, body: agents }),
      "PUT /api/v1/agents/a1": () => {
        agents = [agent({ description: "Reads carefully.", tools: ["read_file"] })];
        return { status: 200, body: agents[0] };
      },
      "DELETE /api/v1/agents/a1": () => {
        agents = [];
        return { status: 204 };
      },
    });
    const user = userEvent.setup();
    renderApp(<App />, "/agents");
    await user.click(await screen.findByRole("button", { name: "Edit Researcher" }));
    const form = screen.getByRole("listitem", { name: "Edit Researcher" });
    const purpose = within(form).getByLabelText("What it is for");
    await user.clear(purpose);
    await user.type(purpose, "Reads carefully.");
    await user.click(within(form).getByLabelText("List files")); // off
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Reads carefully.")).toBeInTheDocument();
    expect(sent(spy, "PUT", "/api/v1/agents/a1")).toEqual({
      name: "Researcher",
      description: "Reads carefully.",
      instructions: "Cite sources.",
      model: null,
      tools: ["read_file"],
    });

    await user.click(screen.getByRole("button", { name: "Delete Researcher" }));
    const confirm = screen.getByRole("group", { name: "Delete Researcher?" });
    await user.click(within(confirm).getByRole("button", { name: "Keep" }));
    expect(spy.mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Delete Researcher" }));
    await user.click(
      within(screen.getByRole("group", { name: "Delete Researcher?" })).getByRole("button", {
        name: "Delete",
      }),
    );
    expect(await screen.findByText("No agents yet")).toBeInTheDocument();
  });
});
