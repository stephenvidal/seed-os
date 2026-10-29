import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

const PAGE = "<!doctype html><html><body><h1>Hi</h1><script>alert(1)</script></body></html>";

describe("Markdown", () => {
  it("renders a table as a table", () => {
    render(<Markdown text={"| a | b |\n|---|---|\n| 1 | 2 |"} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("renders a fenced html block in a script-free sandbox, with the source one switch away", async () => {
    const user = userEvent.setup();
    render(<Markdown text={"Here:\n\n```html\n<h1>Hello</h1>\n```"} />);
    const frame = screen.getByTitle("Rendered html");
    expect(frame.getAttribute("sandbox")).toBe(""); // no scripts, no same-origin
    expect(frame.getAttribute("srcdoc")).toContain("<h1>Hello</h1>");
    expect(frame.getAttribute("srcdoc")).toContain("default-src 'none'");
    expect(screen.queryByText("<h1>Hello</h1>")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByText("<h1>Hello</h1>")).toBeInTheDocument();
    expect(screen.queryByTitle("Rendered html")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Rendered" }));
    expect(screen.getByTitle("Rendered html")).toBeInTheDocument();
  });

  it("renders a fenced markdown block, and leaves other languages as code", async () => {
    render(<Markdown text={"```md\n# Title\n```\n\n```python\nprint('x')\n```"} />);
    expect(screen.getByRole("heading", { level: 1, name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("print('x')")).toBeInTheDocument();
    expect(screen.getAllByRole("group", { name: "View" })).toHaveLength(1);
  });

  it("renders an answer that is a whole page as a page", () => {
    render(<Markdown text={PAGE} />);
    expect(screen.getByTitle("Rendered HTML")).toBeInTheDocument();
  });

  it("shows HTML as code while the answer is still arriving", () => {
    render(<Markdown text={"```html\n<h1>Hello</h1>\n```"} live />);
    expect(screen.queryByTitle("Rendered html")).toBeNull();
    expect(screen.getByText("<h1>Hello</h1>")).toBeInTheDocument();
  });

  it("never injects raw HTML into SEED's own page", () => {
    const { container } = render(<Markdown text={"<img src=x onerror=alert(1)>ok"} />);
    expect(container.querySelector("img")).toBeNull();
  });

  it("with toggle, switches the whole answer to its source", async () => {
    const user = userEvent.setup();
    render(<Markdown text={"Here is **bold**."} toggle />);
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    await user.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByText("Here is **bold**.")).toBeInTheDocument();
  });

  it("starts in the phone view on a phone and offers the desktop view", async () => {
    const mq = window.matchMedia;
    window.matchMedia = ((q: string) => ({ ...mq(q), matches: true })) as typeof mq;
    try {
      const user = userEvent.setup();
      render(<Markdown text={"```html\n<p>x</p>\n```"} />);
      const group = screen.getByRole("group", { name: "Device view" });
      expect(group.querySelector("[aria-pressed=true]")).toHaveTextContent("Phone");
      await user.click(screen.getByRole("button", { name: "Desktop" }));
      expect(group.querySelector("[aria-pressed=true]")).toHaveTextContent("Desktop");
    } finally {
      window.matchMedia = mq;
    }
  });

  it("starts in the desktop view on a wide screen", () => {
    render(<Markdown text={"```html\n<p>x</p>\n```"} />);
    const group = screen.getByRole("group", { name: "Device view" });
    expect(group.querySelector("[aria-pressed=true]")).toHaveTextContent("Desktop");
  });
});
