import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../lib/api";
import { MAX_NOTE_CHARS } from "../lib/projects";
import { Button } from "./ui/Button";
import { Panel } from "./ui/Panel";
import { Spinner } from "./ui/Spinner";

/** What the notes list needs of a note: project memory and memory about the owner. */
export type MemoryNote = {
  id: string;
  content: string;
  /** Only approved notes reach the model. */
  status: "proposed" | "approved";
  /** "agent", or the owner who wrote it. */
  created_by: string;
  source_conversation_id: string | null;
};

export type NotesApi = {
  list: () => Promise<MemoryNote[]>;
  /** The owner's own note, approved as written. */
  add: (content: string) => Promise<unknown>;
  update: (id: string, body: { content?: string; approve?: boolean }) => Promise<unknown>;
  /** Deletes a note, or rejects a proposal. */
  remove: (id: string) => Promise<unknown>;
};

const field =
  "rounded-control border border-border bg-surface-1 px-2.5 text-sm text-fg outline-none focus:border-accent";
const tidy = (text: string) => text.split(/\s+/).filter(Boolean).join(" ");

function Failure({ error }: { error: Error }) {
  return (
    <div className="flex items-start gap-2 px-4 py-4 text-sm text-danger" role="alert">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
      {error instanceof ApiError ? error.message : "Unexpected error."}
    </div>
  );
}

function Loading() {
  return (
    <div className="flex items-center gap-2 px-4 py-6 text-sm text-fg-muted">
      <Spinner /> Loading…
    </div>
  );
}

function Note({
  note,
  api,
  onChanged,
}: {
  note: MemoryNote;
  api: NotesApi;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(note.content);
  const done = onChanged;
  const update = useMutation({
    mutationFn: (body: { content?: string; approve?: boolean }) => api.update(note.id, body),
    onSuccess: () => {
      setEditing(false);
      done();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.remove(note.id),
    onSuccess: done,
  });
  const proposed = note.status === "proposed";
  const busy = update.isPending || remove.isPending;
  const failure = update.error ?? remove.error;

  return (
    <li className="flex flex-col gap-2 px-4 py-3">
      {editing ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (tidy(text)) update.mutate({ content: tidy(text), approve: proposed });
          }}
        >
          <textarea
            aria-label="Note"
            value={text}
            maxLength={MAX_NOTE_CHARS}
            rows={2}
            autoFocus
            onChange={(e) => setText(e.target.value)}
            className={`resize-y py-1.5 ${field}`}
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" size="sm" disabled={busy || !tidy(text)}>
              {proposed ? "Save and approve" : "Save"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <p className="text-sm break-words text-fg">{note.content}</p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
        <span className="min-w-0 flex-1">
          {note.created_by === "agent" ? "Proposed by SEED" : `Added by ${note.created_by}`}
          {note.source_conversation_id && (
            <>
              {" in "}
              <Link
                to={`/chat/${note.source_conversation_id}`}
                className="text-accent hover:underline"
              >
                its chat
              </Link>
            </>
          )}
        </span>
        {!editing && (
          <>
            {proposed && (
              <Button
                size="sm"
                variant="primary"
                disabled={busy}
                onClick={() => update.mutate({ approve: true })}
              >
                Approve
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setText(note.content);
                update.reset();
                setEditing(true);
              }}
            >
              Edit
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => remove.mutate()}>
              {proposed ? "Reject" : "Delete"}
            </Button>
          </>
        )}
      </div>
      {failure && (
        <p role="alert" className="text-xs text-danger">
          {failure instanceof ApiError ? failure.message : "Unexpected error."}
        </p>
      )}
    </li>
  );
}

export function MemoryNotes({
  title,
  intro,
  placeholder,
  queryKey,
  api,
  onChanged,
}: {
  title: string;
  intro: string;
  placeholder: string;
  queryKey: readonly unknown[];
  api: NotesApi;
  /** Called after any change, for views that show counts of waiting notes. */
  onChanged?: () => void;
}) {
  const qc = useQueryClient();
  const memory = useQuery({ queryKey, queryFn: api.list, retry: false });
  const changed = () => {
    void qc.invalidateQueries({ queryKey });
    onChanged?.();
  };
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: () => api.add(tidy(text)),
    onSuccess: () => {
      setText("");
      changed();
    },
  });
  const proposed = memory.data?.filter((m) => m.status === "proposed") ?? [];
  const approved = memory.data?.filter((m) => m.status === "approved") ?? [];
  return (
    <Panel title={title}>
      <p className="px-4 pt-3 text-xs text-fg-muted">{intro}</p>
      {memory.isPending ? (
        <Loading />
      ) : memory.isError ? (
        <Failure error={memory.error} />
      ) : (
        <>
          {proposed.length > 0 && (
            <section aria-label="Waiting for you" className="mt-3">
              <h3 className="border-y border-border bg-accent-soft px-4 py-1.5 text-xs font-semibold text-accent-soft-fg">
                Waiting for you ({proposed.length})
              </h3>
              <ul className="divide-y divide-border">
                {proposed.map((m) => (
                  <Note key={m.id} note={m} api={api} onChanged={changed} />
                ))}
              </ul>
            </section>
          )}
          {approved.length > 0 ? (
            <ul
              aria-label="Remembered"
              className="mt-3 divide-y divide-border border-t border-border"
            >
              {approved.map((m) => (
                <Note key={m.id} note={m} api={api} onChanged={changed} />
              ))}
            </ul>
          ) : (
            proposed.length === 0 && (
              <p className="px-4 pt-3 text-sm text-fg-muted">Nothing remembered yet.</p>
            )
          )}
        </>
      )}
      <form
        className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3 mt-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (tidy(text)) add.mutate();
        }}
      >
        <input
          aria-label="New note"
          placeholder={placeholder}
          value={text}
          maxLength={MAX_NOTE_CHARS}
          onChange={(e) => setText(e.target.value)}
          className={`h-8 min-w-0 flex-1 ${field}`}
        />
        <Button type="submit" size="sm" disabled={add.isPending || !tidy(text)}>
          <Plus size={14} aria-hidden /> Add
        </Button>
        {add.isError && (
          <p role="alert" className="w-full text-xs text-danger">
            {add.error instanceof ApiError ? add.error.message : "Unexpected error."}
          </p>
        )}
      </form>
    </Panel>
  );
}
