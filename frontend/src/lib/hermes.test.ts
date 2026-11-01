import { describe, expect, it } from "vitest";
import { batches, readSessions, textOf } from "./hermes";
import type { HermesSession, SqlDb } from "./hermes";

/** A fake state.db answering the few queries readSessions makes. */
function fakeDb(
  sessions: Record<string, unknown>[],
  messages: Record<string, unknown>[],
  sessionColumns = ["id", "title", "source", "model", "started_at"],
): SqlDb {
  const table = (rows: Record<string, unknown>[], columns: string[]) =>
    rows.length ? [{ columns, values: rows.map((r) => columns.map((c) => r[c] ?? null)) }] : [];
  return {
    exec: (sql) => {
      if (sql === "PRAGMA table_info(sessions)")
        return table(
          sessionColumns.map((name) => ({ name })),
          ["name"],
        );
      if (sql === "PRAGMA table_info(messages)")
        return table(
          ["session_id", "role", "content"].map((name) => ({ name })),
          ["name"],
        );
      if (sql.startsWith("SELECT id")) {
        const cols = ["id", "title", "source", "model", "started_at"];
        return table(
          sessions.map((s) =>
            Object.fromEntries(cols.map((c) => [c, sessionColumns.includes(c) ? s[c] : null])),
          ),
          cols,
        );
      }
      return table(
        messages.filter((m) => m.role === "user" || m.role === "assistant"),
        ["session_id", "role", "content", "timestamp"],
      );
    },
  };
}

describe("reading a Hermes state.db", () => {
  it("keeps chats with their user and assistant text, and leaves out the rest", () => {
    const db = fakeDb(
      [
        { id: "a", title: "Backups", source: "telegram", model: "m", started_at: 100 },
        { id: "b", title: null, source: "subagent", model: "m", started_at: 200 },
        { id: "c", title: null, source: "cli", model: null, started_at: 300 },
      ],
      [
        { session_id: "a", role: "user", content: "Where?", timestamp: 101 },
        { session_id: "a", role: "assistant", content: "", timestamp: 102 },
        { session_id: "a", role: "tool", content: "ls output", timestamp: 103 },
        {
          session_id: "a",
          role: "assistant",
          content: '\u0000json:[{"type":"text","text":"On the NAS."}]',
          timestamp: 104,
        },
        { session_id: "b", role: "user", content: "internal", timestamp: 201 },
        { session_id: "c", role: "assistant", content: "Hello", timestamp: 301 },
      ],
    );
    expect(readSessions(db)).toEqual([
      {
        id: "a",
        title: "Backups",
        source: "telegram",
        model: "m",
        started_at: 100,
        messages: [
          { role: "user", content: "Where?", timestamp: 101 },
          { role: "assistant", content: "On the NAS.", timestamp: 104 },
        ],
      },
    ]);
  });

  it("copes with an older file without titles, and refuses one that is not Hermes'", () => {
    const old = fakeDb(
      [{ id: "a", source: "cli", started_at: 1 }],
      [{ session_id: "a", role: "user", content: "hi", timestamp: 2 }],
      ["id", "source", "started_at"],
    );
    expect(readSessions(old)[0]).toMatchObject({ id: "a", title: null, model: null });
    expect(() => readSessions(fakeDb([], [], ["x"]))).toThrow(/not a Hermes Agent state.db/);
  });

  it("reads structured content's text parts and nothing else", () => {
    expect(textOf("plain")).toBe("plain");
    expect(textOf('\u0000json:[{"type":"image_url"},{"type":"text","text":"a"},"b"]')).toBe("a\nb");
    expect(textOf("\u0000json:{broken")).toBe("");
    expect(textOf(null)).toBe("");
  });

  it("splits sessions into requests the web server lets through", () => {
    const s = (id: string, size: number): HermesSession => ({
      id,
      title: null,
      source: null,
      model: null,
      started_at: 0,
      messages: [{ role: "user", content: "x".repeat(size), timestamp: 0 }],
    });
    const big = batches([s("a", 900_000), s("b", 900_000), s("c", 10)]);
    expect(big.map((b) => b.map((x) => x.id))).toEqual([["a"], ["b", "c"]]);
    const many = batches(Array.from({ length: 120 }, (_, i) => s(String(i), 1)));
    expect(many.map((b) => b.length)).toEqual([50, 50, 20]);
  });
});

describe("against a real SQLite file", () => {
  it("reads a database shaped like Hermes' state.db", async () => {
    const { default: initSqlJs } = await import("sql.js");
    const SQL = await initSqlJs();
    const db = new SQL.Database();
    db.run(`
      CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, model TEXT,
        started_at REAL NOT NULL, ended_at REAL, title TEXT);
      CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
        role TEXT NOT NULL, content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT,
        timestamp REAL NOT NULL);
      INSERT INTO sessions VALUES ('s1', 'telegram', 'hermes-3', 1772360100.5, NULL, 'Plan');
      INSERT INTO sessions VALUES ('s2', 'tool', NULL, 1772360200, NULL, NULL);
      INSERT INTO messages (session_id, role, content, timestamp) VALUES
        ('s1', 'session_meta', '{}', 1772360100.6),
        ('s1', 'user', 'Nightly backups?', 1772360101),
        ('s1', 'assistant', NULL, 1772360102),
        ('s1', 'tool', 'ok', 1772360103),
        ('s1', 'assistant', 'Yes, at 02:00.', 1772360104),
        ('s2', 'user', 'internal', 1772360201);
    `);
    const [session] = readSessions(db);
    db.close();
    expect(session).toEqual({
      id: "s1",
      title: "Plan",
      source: "telegram",
      model: "hermes-3",
      started_at: 1772360100.5,
      messages: [
        { role: "user", content: "Nightly backups?", timestamp: 1772360101 },
        { role: "assistant", content: "Yes, at 02:00.", timestamp: 1772360104 },
      ],
    });
  });
});
