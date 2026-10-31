import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { useState } from "react";
import type { ChangeEvent } from "react";
import { ApiError } from "../lib/api";
import { OWNER_MEMORY, ownerMemoryApi } from "../lib/memory";
import type { HermesImport } from "../lib/memory";
import { Button } from "./ui/Button";
import { Panel } from "./ui/Panel";

const REASON: Record<HermesImport["skipped"][number]["reason"], string> = {
  duplicate: "already a note",
  too_long: "longer than 500 characters",
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const message = (e: Error) => (e instanceof ApiError ? e.message : "Unexpected error.");

/** Bring in a Hermes Agent memory file as notes about the owner (D-042). */
export function HermesMemoryImport() {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const preview = useMutation({ mutationFn: () => ownerMemoryApi.importHermes(text, true) });
  const save = useMutation({
    mutationFn: () => ownerMemoryApi.importHermes(text, false),
    onSuccess: () => void qc.invalidateQueries({ queryKey: OWNER_MEMORY }),
  });

  function reset(next = "") {
    setText(next);
    setError(null);
    preview.reset();
    save.reset();
  }

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      reset(await file.text());
    } catch {
      setError(`Could not read ${file.name}.`);
    }
  }

  const plan = preview.data;
  const failure =
    error ?? (preview.error || save.error ? message((preview.error ?? save.error) as Error) : null);

  return (
    <Panel title="Import from Hermes Agent">
      <div className="flex flex-col gap-3 px-4 py-4 text-sm">
        <p className="text-xs text-fg-muted">
          Choose USER.md or MEMORY.md from <span className="font-mono">~/.hermes/memories/</span>,
          or paste it. Each entry becomes a note above, approved, since you chose the file.
        </p>
        {save.isSuccess ? (
          <div role="status" className="flex items-center justify-between gap-3">
            <p className="text-fg">Added {plural(save.data.added.length, "note")}.</p>
            <Button size="sm" onClick={() => reset()}>
              Import another
            </Button>
          </div>
        ) : (
          <>
            <textarea
              aria-label="Hermes memory file"
              value={text}
              rows={5}
              onChange={(e) => reset(e.target.value)}
              placeholder={"Name: Stephen\n§\nPrefers short answers"}
              className="resize-y rounded-control border border-border bg-surface-1 px-2.5 py-2 font-mono text-xs text-fg outline-none focus:border-accent"
            />
            <div className="flex items-center justify-between gap-3">
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-fg-muted">
                <FileUp size={14} aria-hidden />
                Or choose a file
                <input
                  type="file"
                  accept=".md,text/markdown,text/plain"
                  onChange={pick}
                  className="sr-only"
                />
              </label>
              {!plan && (
                <Button
                  size="sm"
                  disabled={!text.trim() || preview.isPending}
                  onClick={() => preview.mutate()}
                >
                  {preview.isPending ? "Reading…" : "Preview"}
                </Button>
              )}
            </div>
            {plan && (
              <section aria-label="Import preview" className="flex flex-col gap-2">
                {plan.added.length > 0 ? (
                  <ul className="flex flex-col gap-1">
                    {plan.added.map((n) => (
                      <li key={n} className="rounded-control bg-surface-2 px-2.5 py-1.5 text-fg">
                        {n}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-fg-muted">Nothing new to add.</p>
                )}
                {plan.skipped.length > 0 && (
                  <ul className="flex flex-col gap-1 text-xs text-fg-muted">
                    {plan.skipped.map((s, i) => (
                      <li key={i}>
                        Skipped, {REASON[s.reason]}: {s.content.slice(0, 120)}
                        {s.content.length > 120 ? "…" : ""}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="flex justify-end gap-2">
                  <Button size="sm" onClick={() => reset()}>
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={plan.added.length === 0 || save.isPending}
                    onClick={() => save.mutate()}
                  >
                    {save.isPending ? "Importing…" : `Import ${plural(plan.added.length, "note")}`}
                  </Button>
                </div>
              </section>
            )}
          </>
        )}
        {failure && (
          <p role="alert" className="text-xs text-danger">
            {failure}
          </p>
        )}
      </div>
    </Panel>
  );
}
