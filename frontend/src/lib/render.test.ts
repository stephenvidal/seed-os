import { describe, expect, it } from "vitest";
import { frameLayout, isHtmlDocument, kindForLanguage, prepareHtml } from "./render";

describe("kindForLanguage", () => {
  it("renders html, svg and markdown fences and nothing else", () => {
    expect(kindForLanguage("html")).toBe("html");
    expect(kindForLanguage("SVG")).toBe("html");
    expect(kindForLanguage("md")).toBe("markdown");
    expect(kindForLanguage("python")).toBeNull();
    expect(kindForLanguage(undefined)).toBeNull();
  });
});

describe("isHtmlDocument", () => {
  it("accepts a whole page and rejects prose that mentions html", () => {
    expect(isHtmlDocument("\n<!DOCTYPE html><html></html>")).toBe(true);
    expect(isHtmlDocument("<html lang='en'>")).toBe(true);
    expect(isHtmlDocument("Use <html> to start a page")).toBe(false);
  });
});

describe("prepareHtml", () => {
  it("puts the policy and viewport in the head, before the page's own head content", () => {
    const out = prepareHtml(
      "<!doctype html><html><head><title>x</title></head><body>hi</body></html>",
    );
    expect(out.indexOf("Content-Security-Policy")).toBeLessThan(out.indexOf("<title>"));
    expect(out).toContain('name="viewport"');
    expect(out).toContain("max-width:100%");
  });
  it("wraps a fragment so it still gets the policy, in standards mode", () => {
    const out = prepareHtml("<h1>Hi</h1>");
    expect(out.startsWith("<!doctype html>")).toBe(true);
    expect(out).toContain("Content-Security-Policy");
    expect(out).toContain("<h1>Hi</h1>");
  });
  it("adds a head to a page that has none", () => {
    const out = prepareHtml("<!doctype html><html><body>a</body></html>");
    expect(out).toMatch(/<html><head><meta http-equiv="Content-Security-Policy"/);
  });
  it("keeps the policy ahead of a doctype-only page's content", () => {
    const out = prepareHtml("<!doctype html><p>a</p>");
    expect(out.startsWith("<!doctype html><head>")).toBe(true);
  });
  it("forbids network and scripts", () => {
    const out = prepareHtml("<p>a</p>");
    expect(out).toContain("default-src 'none'");
    expect(out).not.toContain("script-src");
  });
});

describe("frameLayout", () => {
  it("fills a phone and centres a phone-width frame on a wide screen", () => {
    expect(frameLayout("phone", 360)).toEqual({ width: 360, scale: 1 });
    expect(frameLayout("phone", 900)).toEqual({ width: 390, scale: 1 });
  });
  it("shrinks the desktop window to fit a narrow screen and never enlarges it", () => {
    expect(frameLayout("desktop", 512)).toEqual({ width: 1024, scale: 0.5 });
    expect(frameLayout("desktop", 2000)).toEqual({ width: 1024, scale: 1 });
  });
});
