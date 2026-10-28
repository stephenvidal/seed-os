import { describe, expect, it } from "vitest";
import { parseSse } from "./runs";

describe("parseSse", () => {
  it("parses complete events, skips comments, and keeps the partial remainder", () => {
    const buf =
      'id: 1\nevent: text_delta\ndata: {"text":"Hel"}\n\n' +
      ": keepalive\n\n" +
      'id: 2\nevent: run_finished\ndata: {"termination":"completed"}\n\n' +
      "id: 3\nevent: text_de";
    const { events, rest } = parseSse(buf);
    expect(events).toEqual([
      { type: "text_delta", data: { text: "Hel" } },
      { type: "run_finished", data: { termination: "completed" } },
    ]);
    expect(rest).toBe("id: 3\nevent: text_de");
  });
});
