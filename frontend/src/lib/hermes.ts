/**
 * Past Hermes Agent sessions (D-045): read from Hermes' state.db in the browser and
 * sent to SEED in batches. Only user messages and assistant text are sent.
 */
import { request } from "./api";

export type HermesMessage = { role: "user" | "assistant"; content: string; timestamp: number };

export type HermesSession = {
  id: string;
  title: string | null;
  source: string | null;
  model: string | null;
  started_at: number;
  messages: HermesMessage[];
};

export type SessionResult = {
  id: string;
  outcome: "imported" | "already_imported" | "empty";
  turns: number;
  conversation_id: string | null;
};

/** The part of a SQLite database this module needs (sql.js's Database fits it). */
export type SqlDb = {
  exec: (sql: string) => { columns: string[]; values: unknown[][] }[];
};

/** Hermes' own background sessions, not chats with the owner. */
const INTERNAL = new Set(["tool", "subagent", "kanban", "oneshot"]);
// Hermes stores structured message content as JSON after this prefix.
const JSON_PREFIX = "\u0000json:";
const MAX_CONTENT = 100_000;
// Keep each request well under the 2 MB the web server lets through.
const BATCH_BYTES = 1_500_000;
const BATCH_SESSIONS = 50;

function rows(db: SqlDb, sql: string): Record<string, unknown>[] {
  const [result] = db.exec(sql);
  if (!result) return [];
  return result.values.map((v) => Object.fromEntries(result.columns.map((c, i) => [c, v[i]])));
}

function columnsOf(db: SqlDb, table: string): Set<string> {
  return new Set(rows(db, `PRAGMA table_info(${table})`).map((r) => String(r.name)));
}

/** The text of a stored message: plain, or the text parts of structured content. */
export function textOf(content: unknown): string {
  if (typeof content !== "string") return "";
  if (!content.startsWith(JSON_PREFIX)) return content;
  try {
    const parsed: unknown = JSON.parse(content.slice(JSON_PREFIX.length));
    const parts = Array.isArray(parsed) ? parsed : [parsed];
    return parts
      .map((p) =>
        typeof p === "string"
          ? p
          : p && typeof p === "object" && typeof (p as { text?: unknown }).text === "string"
            ? (p as { text: string }).text
            : "",
      )
      .filter(Boolean)
      .join("\n");
  } catch {
    return "";
  }
}

const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);

/** Every chat session in a Hermes state.db with its user and assistant text, oldest first. */
export function readSessions(db: SqlDb): HermesSession[] {
  const have = columnsOf(db, "sessions");
  if (!have.has("id") || !have.has("started_at") || !columnsOf(db, "messages").has("role")) {
    throw new Error("This is not a Hermes Agent state.db: it has no sessions and messages.");
  }
  const pick = (c: string) => (have.has(c) ? c : `NULL AS ${c}`);
  const sessions = new Map<string, HermesSession>();
  for (const r of rows(
    db,
    `SELECT id, ${pick("title")}, ${pick("source")}, ${pick("model")}, started_at ` +
      "FROM sessions ORDER BY started_at, id",
  )) {
    if (INTERNAL.has(String(r.source))) continue;
    sessions.set(String(r.id), {
      id: String(r.id),
      title: str(r.title),
      source: str(r.source),
      model: str(r.model),
      started_at: Number(r.started_at) || 0,
      messages: [],
    });
  }
  for (const r of rows(
    db,
    "SELECT session_id, role, content, timestamp FROM messages " +
      "WHERE role IN ('user', 'assistant') ORDER BY session_id, timestamp, id",
  )) {
    const session = sessions.get(String(r.session_id));
    const text = textOf(r.content).slice(0, MAX_CONTENT);
    if (!session || !text.trim()) continue;
    session.messages.push({
      role: r.role as HermesMessage["role"],
      content: text,
      timestamp: Number(r.timestamp) || session.started_at,
    });
  }
  return [...sessions.values()].filter((s) => s.messages.some((m) => m.role === "user"));
}

/** Sessions in requests the server and the web server accept. */
export function batches(sessions: HermesSession[]): HermesSession[][] {
  const out: HermesSession[][] = [];
  let current: HermesSession[] = [];
  let size = 0;
  for (const s of sessions) {
    const bytes = new TextEncoder().encode(JSON.stringify(s)).length;
    if (current.length && (size + bytes > BATCH_BYTES || current.length >= BATCH_SESSIONS)) {
      out.push(current);
      current = [];
      size = 0;
    }
    current.push(s);
    size += bytes;
  }
  if (current.length) out.push(current);
  return out;
}

export const hermesApi = {
  importSessions: (sessions: HermesSession[]) =>
    request<SessionResult[]>("/api/v1/conversations/import-hermes", {
      method: "POST",
      body: JSON.stringify({ sessions }),
    }),
};

/** Open a state.db file with sql.js, loaded only when needed. */
export async function openStateDb(file: File): Promise<SqlDb & { close: () => void }> {
  const [{ default: initSqlJs }, { default: wasmUrl }] = await Promise.all([
    import("sql.js"),
    import("sql.js/dist/sql-wasm.wasm?url"),
  ]);
  const SQL = await initSqlJs({ locateFile: () => wasmUrl });
  return new SQL.Database(new Uint8Array(await file.arrayBuffer()));
}
