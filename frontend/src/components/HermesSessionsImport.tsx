import { useQueryClient } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { useState } from "react";
import type { ChangeEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../lib/api";
import { batches, hermesApi, openStateDb, readSessions } from "../lib/hermes";
import type { HermesSession } from "../lib/hermes";
import { Button } from "./ui/Button";
import { Spinner } from "./ui/Spinner";

// The Chat page lists conversations under this key.
const CONVERSATIONS = ["conversations"] as const;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const day = (seconds: number) => new Date(seconds * 1000).toISOString().slice(0, 10);

type Done = { imported: number; turns: number; before: number; failed: number };

/** Past Hermes Agent sessions as chats (D-045): choose state.db, check, import. */
export function HermesSessionsImport() {
  const qc = useQueryClient();
  const [sessions, setSessions] = useState<HermesSession[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Done | null>(null);

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setDone(null);
    setSessions(null);
    setBusy(`Reading ${file.name}…`);
    try {
      const db = await openStateDb(file);
      try {
        setSessions(readSessions(db));
      } finally {
        db.close();
      }
    } catch (err) {
      setError(
        err instanceof Error && err.message.startsWith("This is not")
          ? err.message
          : `Could not read ${file.name} as a SQLite database.`,
      );
    } finally {
      setBusy(null);
    }
  }

  async function importAll() {
    if (!sessions) return;
    const parts = batches(sessions);
    const tally: Done = { imported: 0, turns: 0, before: 0, failed: 0 };
    setError(null);
    for (const [i, part] of parts.entries()) {
      setBusy(`Importing… ${i + 1} of ${parts.length}`);
      try {
        for (const r of await hermesApi.importSessions(part)) {
          if (r.outcome === "imported") {
            tally.imported += 1;
            tally.turns += r.turns;
          } else if (r.outcome === "already_imported") tally.before += 1;
        }
      } catch (err) {
        tally.failed += part.length;
        if (err instanceof ApiError && err.status === 401) {
          setError(err.message);
          break;
        }
      }
    }
    setBusy(null);
    setDone(tally);
    setSessions(null);
    await qc.invalidateQueries({ queryKey: CONVERSATIONS });
  }

  const messages = sessions?.reduce((n, s) => n + s.messages.length, 0) ?? 0;
  return (
    <section
      aria-label="Past chats"
      className="flex flex-col gap-3 border-t border-border px-4 py-4 text-sm"
    >
      <p className="text-xs text-fg-muted">
        Past chats: choose <span className="font-mono">~/.hermes/state.db</span> (stop Hermes first,
        so its latest chats are in the file). It is read in your browser; only what you and Hermes
        wrote is sent. Each session becomes a chat in SEED, found by its past-chat search.
      </p>
      <label className="flex w-fit cursor-pointer items-center gap-1.5 text-xs text-fg-muted">
        <FileUp size={14} aria-hidden />
        Choose state.db
        <input type="file" onChange={pick} className="sr-only" disabled={busy !== null} />
      </label>
      {busy && (
        <p className="flex items-center gap-2 text-fg-muted" role="status">
          <Spinner /> {busy}
        </p>
      )}
      {sessions && !busy && (
        <div className="flex items-center justify-between gap-3" role="status">
          <p className="text-fg">
            {sessions.length === 0
              ? "No chats found in that file."
              : `${plural(sessions.length, "session")}, ${plural(messages, "message")}, from ${day(
                  sessions[0]!.started_at,
                )} to ${day(sessions[sessions.length - 1]!.started_at)}.`}
          </p>
          {sessions.length > 0 && (
            <Button variant="primary" size="sm" onClick={() => void importAll()}>
              Import {plural(sessions.length, "session")}
            </Button>
          )}
        </div>
      )}
      {done && (
        <p role="status" className="text-fg">
          Imported {plural(done.imported, "session")} ({plural(done.turns, "turn")}).
          {done.before > 0 && ` ${plural(done.before, "session")} were already here.`}
          {done.failed > 0 && ` ${plural(done.failed, "session")} could not be imported.`}{" "}
          <Link to="/chat" className="text-accent underline">
            Open Chat
          </Link>
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </section>
  );
}
