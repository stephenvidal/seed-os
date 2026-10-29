import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { App } from "./App";
import { mockApi, renderApp } from "./test/render";

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

const OVERVIEW = {
  status: 200,
  body: {
    window_hours: 24,
    generated_at: "2026-10-29T12:00:00Z",
    counts: { queued: 0, running: 0, waiting: 0, completed: 0, failed: 0, canceled: 0 },
    attention: [],
    active: [],
    recent: [],
    usage: [],
  },
};

describe("authentication gate", () => {
  it("shows sign-in when signed out, surfaces errors, and enters the shell on success", async () => {
    let signedIn = false;
    mockApi({
      "GET /api/v1/auth/me": () =>
        signedIn ? ME : { status: 401, body: { error: { code: "unauthenticated", message: "x" } } },
      "POST /api/v1/auth/login": () => {
        signedIn = true;
        return ME;
      },
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/overview?hours=24": OVERVIEW,
    });
    const user = userEvent.setup();
    const { container } = renderApp(<App />);
    const pw = await screen.findByLabelText("Password");
    expect(await axe(container)).toHaveNoViolations();
    await user.type(pw, "secret");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("heading", { level: 1, name: /admin/ })).toBeInTheDocument();
    expect(await screen.findByText("4.0 GB")).toBeInTheDocument(); // real used memory = total - available
  });

  it("shows the server's message on bad credentials", async () => {
    mockApi({
      "GET /api/v1/auth/me": {
        status: 401,
        body: { error: { code: "unauthenticated", message: "x" } },
      },
      "POST /api/v1/auth/login": {
        status: 401,
        body: {
          error: { code: "invalid_credentials", message: "Incorrect username or password." },
        },
      },
    });
    const user = userEvent.setup();
    renderApp(<App />);
    await user.type(await screen.findByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect username or password.");
  });

  it("shows a retryable error when the API is unreachable", async () => {
    mockApi({});
    renderApp(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the SEED API.");
  });
});

describe("workspace shell", () => {
  it("navigates with the command palette and the G-chord, and passes axe", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/overview?hours=24": OVERVIEW,
    });
    const user = userEvent.setup();
    const { container } = renderApp(<App />);
    await screen.findByText("System health");
    expect(await axe(container)).toHaveNoViolations();

    await user.keyboard("{Control>}k{/Control}");
    const input = await screen.findByPlaceholderText(/type a command/i);
    await user.type(input, "studio");
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { level: 1, name: "Studio" })).toBeInTheDocument();

    await user.keyboard("gt");
    expect(await screen.findByRole("heading", { level: 1, name: "Tasks" })).toBeInTheDocument();
  });

  it("changes theme from Settings and persists it", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/overview?hours=24": OVERVIEW,
    });
    const user = userEvent.setup();
    renderApp(<App />, "/settings");
    await user.click(await screen.findByRole("radio", { name: /dark/i }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("dark"));
    expect(localStorage.getItem("seed.theme")).toBe("dark");
    expect(screen.getByRole("radio", { name: /dark/i })).toHaveAttribute("aria-checked", "true");
  });

  it("renders a not-found page for unknown routes", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/overview?hours=24": OVERVIEW,
    });
    renderApp(<App />, "/nope");
    expect(await screen.findByText("This page does not exist")).toBeInTheDocument();
  });

  it.each([
    ["signs out", 204],
    ["treats an already-expired session as signed out", 401],
  ])("%s from the account menu", async (_, status) => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/system": SYSTEM,
      "GET /api/v1/overview?hours=24": OVERVIEW,
      "POST /api/v1/auth/logout": { status },
    });
    const user = userEvent.setup();
    renderApp(<App />);
    await user.click(await screen.findByRole("button", { name: "Account menu" }));
    await user.click(await screen.findByRole("menuitem", { name: /Sign out/ }));
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
  });
});
