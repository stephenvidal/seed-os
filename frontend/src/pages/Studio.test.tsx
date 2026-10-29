import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { App } from "../App";
import { mockApi, renderApp } from "../test/render";

const ME = { status: 200, body: { username: "admin", role: "admin" } };

const version = (n: number, over: Record<string, unknown> = {}) => ({
  version: n,
  task_id: `task-${n}`,
  size: 100 * n,
  deleted: false,
  created_at: "2026-10-29T12:00:00Z",
  ...over,
});

const artifact = (over: Record<string, unknown>) => ({
  id: "a1",
  path: "site/index.html",
  media_type: "text/html; charset=utf-8",
  conversation_id: "c1",
  source_title: "Build a site",
  task_id: null,
  versions: 2,
  latest: version(2),
  created_at: "2026-10-29T11:00:00Z",
  updated_at: "2026-10-29T12:00:00Z",
  ...over,
});

afterEach(() => vi.restoreAllMocks());

describe("Studio", () => {
  it("lists saved files by the chat or task that made them", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/artifacts?limit=500": {
        status: 200,
        body: [
          artifact({}),
          artifact({
            id: "a2",
            path: "notes.txt",
            media_type: "text/plain; charset=utf-8",
            conversation_id: null,
            task_id: "t9",
            source_title: "Lone job",
            versions: 3,
            latest: version(3, { deleted: true, size: null }),
          }),
          artifact({ id: "a3", path: "site/style.css", versions: 1, latest: version(1) }),
        ],
      },
    });
    const { container } = renderApp(<App />, "/studio");
    const site = await screen.findByRole("region", { name: "Build a site" });
    expect(within(site).getByRole("link", { name: "Open chat" })).toHaveAttribute(
      "href",
      "/chat/c1",
    );
    const rows = within(site).getAllByRole("link", { name: /site\// });
    expect(rows.map((r) => r.getAttribute("href"))).toEqual(["/studio/a1", "/studio/a3"]);
    expect(rows[0]).toHaveTextContent("2 versions · 200 B");
    expect(rows[1]).toHaveTextContent("1 version · 100 B");

    const lone = screen.getByRole("region", { name: "Lone job" });
    expect(within(lone).getByRole("link", { name: "Open task" })).toHaveAttribute(
      "href",
      "/tasks/t9",
    );
    expect(within(lone).getByRole("link", { name: /notes\.txt/ })).toHaveTextContent("deleted");
    expect(await axe(container)).toHaveNoViolations();
  });

  it("says plainly when nothing is saved yet", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/artifacts?limit=500": { status: 200, body: [] },
    });
    renderApp(<App />, "/studio");
    expect(await screen.findByText("No saved files yet")).toBeInTheDocument();
    expect(screen.queryByText(/Arrives in|M6 ·/)).toBeNull(); // built: no milestone note
  });

  it("previews HTML first in a sandbox, with its source and versions one switch away", async () => {
    const user = userEvent.setup();
    const preview = vi.fn(() => ({
      status: 201,
      body: { url: "/api/v1/previews/tok/site/index.html", expires_in: 3600 },
    }));
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/artifacts/a1": {
        status: 200,
        body: { artifact: artifact({}), versions: [version(2), version(1)] },
      },
      "GET /api/v1/artifacts/a1/versions/2/content": { status: 200, raw: "<h1>new</h1>" },
      "GET /api/v1/artifacts/a1/versions/1/content": { status: 200, raw: "<h1>old</h1>" },
      "POST /api/v1/artifacts/a1/preview": preview,
    });
    const { container } = renderApp(<App />, "/studio/a1");

    // Rendered first: the preview starts by itself, and the source is not shown yet.
    const frame = await screen.findByTitle("Preview of site/index.html");
    expect(preview).toHaveBeenCalledTimes(1);
    expect(frame).toHaveAttribute("src", "/api/v1/previews/tok/site/index.html");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts allow-modals");
    expect(screen.queryByText("<h1>new</h1>")).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "site/index.html" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download v2/ })).toHaveAttribute(
      "href",
      "/api/v1/artifacts/a1/versions/2/content?download=true",
    );
    const versions = screen.getByRole("region", { name: "Versions" });
    expect(within(versions).getAllByRole("link", { name: "Inspect run" })[1]).toHaveAttribute(
      "href",
      "/inspector/task-1",
    );

    await user.click(screen.getByRole("button", { name: "Source" }));
    expect(await screen.findByText("<h1>new</h1>")).toBeInTheDocument();
    expect(screen.queryByTitle("Preview of site/index.html")).toBeNull();
    expect(await axe(container)).toHaveNoViolations(); // axe cannot enter the frame
    await user.click(within(versions).getByRole("button", { name: "Show v1" }));
    expect(await screen.findByText("<h1>old</h1>")).toBeInTheDocument();
    // Previews run the latest files only: no frame and no button for an old version.
    expect(screen.queryByTitle("Preview of site/index.html")).toBeNull();
    expect(screen.queryByRole("button", { name: /Run preview/ })).toBeNull();
    expect(screen.getByText(/Previews run the latest version/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download v1/ })).toBeInTheDocument();
  });

  it("shows images and deleted versions", async () => {
    const user = userEvent.setup();
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/artifacts/img": {
        status: 200,
        body: {
          artifact: artifact({
            id: "img",
            path: "logo.png",
            media_type: "image/png",
            latest: version(2, { deleted: true, size: null }),
          }),
          versions: [version(2, { deleted: true, size: null }), version(1)],
        },
      },
    });
    renderApp(<App />, "/studio/img");
    expect(await screen.findByText("The file was deleted in this version.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Download/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Show v1" }));
    expect(await screen.findByRole("img", { name: "logo.png, version 1" })).toHaveAttribute(
      "src",
      "/api/v1/artifacts/img/versions/1/content",
    );
  });

  it("offers a download for files it cannot show", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/artifacts/zip": {
        status: 200,
        body: {
          artifact: artifact({
            id: "zip",
            path: "out.zip",
            media_type: "application/zip",
            versions: 1,
            latest: version(1),
          }),
          versions: [version(1)],
        },
      },
    });
    renderApp(<App />, "/studio/zip");
    expect(
      await screen.findByText(/No preview for this kind of file \(application\/zip\)/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download v1/ })).toBeInTheDocument();
  });

  it("explains a file that no longer exists", async () => {
    mockApi({
      "GET /api/v1/auth/me": ME,
      "GET /api/v1/artifacts/gone": {
        status: 404,
        body: { error: { code: "not_found", message: "No such artifact." } },
      },
    });
    renderApp(<App />, "/studio/gone");
    expect(await screen.findByText("No such file")).toBeInTheDocument();
  });
});
