import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileUp, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { AGENTS, agentsApi } from "../lib/agents";
import type { Agent } from "../lib/agents";
import { ApiError } from "../lib/api";
import { SKILLS, SKILL_NAME, skillsApi } from "../lib/skills";
import type { Skill, SkillInput } from "../lib/skills";

const field =
  "rounded-control border border-border bg-surface-1 px-2.5 text-sm text-fg outline-none focus:border-accent";
const tidy = (s: string) => s.split(/\s+/).filter(Boolean).join(" ");
const message = (e: Error) => (e instanceof ApiError ? e.message : "Unexpected error.");
const tagsOf = (s: string) => s.split(",").map(tidy).filter(Boolean);

const BLANK: SkillInput = { name: "", description: "", tags: [], body: "", agent_id: null };

/** Shared, or private to one of the owner's agents. */
function WhoSelect({
  agents,
  value,
  onChange,
}: {
  agents: Agent[];
  value: string | null;
  onChange: (agentId: string | null) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-fg-muted sm:max-w-xs">
      Who can use it
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className={`h-8 ${field}`}
      >
        <option value="">SEED, and the agents you allow it</option>
        {agents.map((a) => (
          <option key={a.id} value={a.id}>
            Only {a.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Write or change a skill: every field is sent, as the API replaces the whole skill. */
function SkillForm({
  initial,
  agents,
  submitLabel,
  onSave,
  onCancel,
}: {
  initial: SkillInput;
  agents: Agent[];
  submitLabel: string;
  onSave: (body: SkillInput) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [tags, setTags] = useState(initial.tags.join(", "));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<SkillInput>) => setDraft((d) => ({ ...d, ...patch }));
  const name = draft.name.trim().toLowerCase();
  const badName = name !== "" && !SKILL_NAME.test(name);
  const ready = name && !badName && tidy(draft.description) && draft.body.trim();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        name,
        description: tidy(draft.description),
        tags: tagsOf(tags),
        body: draft.body,
        agent_id: draft.agent_id,
      });
    } catch (err) {
      setError(message(err as Error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 px-4 py-4">
      <div className="grid gap-3 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
        <label className="flex flex-col gap-1 text-xs text-fg-muted">
          Name
          <input
            value={draft.name}
            maxLength={64}
            onChange={(e) => set({ name: e.target.value })}
            placeholder="deploy-site"
            aria-describedby="skill-name-rule"
            className={`h-8 font-mono ${field}`}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-fg-muted">
          What it is for
          <input
            value={draft.description}
            maxLength={1024}
            onChange={(e) => set({ description: e.target.value })}
            placeholder="Ship the site to the server and check it is up"
            className={`h-8 ${field}`}
          />
        </label>
      </div>
      <p id="skill-name-rule" className={`text-xs ${badName ? "text-danger" : "text-fg-muted"}`}>
        Lower-case letters, digits and hyphens. Start a message with /{name || "name"} to use it.
      </p>
      <label className="flex flex-col gap-1 text-xs text-fg-muted">
        Instructions
        <textarea
          value={draft.body}
          maxLength={20000}
          rows={8}
          onChange={(e) => set({ body: e.target.value })}
          placeholder={"When to use it, the steps, pitfalls, and how to check the result"}
          className={`resize-y py-2 font-mono text-xs ${field}`}
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-fg-muted">
          Tags (comma separated)
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="ops, web"
            className={`h-8 ${field}`}
          />
        </label>
        <WhoSelect
          agents={agents}
          value={draft.agent_id}
          onChange={(id) => set({ agent_id: id })}
        />
      </div>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="sm" disabled={!ready || saving}>
          {saving ? "Saving…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}

/** Paste or upload a Hermes Agent SKILL.md. */
function ImportForm({ agents, onDone }: { agents: Agent[]; onDone: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [agentId, setAgentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: () => skillsApi.import(text, agentId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: SKILLS }),
  });

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    try {
      setText(await file.text());
    } catch {
      setError(`Could not read ${file.name}.`);
    }
  }

  if (run.isSuccess) {
    const { skill, ignored } = run.data;
    return (
      <div className="flex flex-col gap-2 px-4 py-4 text-sm" role="status">
        <p className="text-fg">
          Imported <span className="font-mono">{skill.name}</span>.
        </p>
        {ignored.length > 0 && (
          <p className="text-xs text-fg-muted">
            SEED does not use these parts of its header: {ignored.join(", ")}.
          </p>
        )}
        <div className="flex justify-end">
          <Button size="sm" onClick={onDone}>
            Done
          </Button>
        </div>
      </div>
    );
  }
  return (
    <form
      className="flex flex-col gap-3 px-4 py-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) run.mutate();
      }}
    >
      <label className="flex flex-col gap-1 text-xs text-fg-muted">
        SKILL.md
        <textarea
          value={text}
          rows={8}
          onChange={(e) => setText(e.target.value)}
          placeholder={"---\nname: deploy-site\ndescription: Ship the site\n---\n# Steps…"}
          className={`resize-y py-2 font-mono text-xs ${field}`}
        />
      </label>
      <div className="flex flex-wrap items-end gap-3">
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
        <WhoSelect agents={agents} value={agentId} onChange={setAgentId} />
      </div>
      <p className="text-xs text-fg-muted">
        SEED keeps the name, description, tags and instructions. Files beside a SKILL.md, such as
        references or scripts, are not imported.
      </p>
      {(error ?? run.error) && (
        <p role="alert" className="text-xs text-danger">
          {error ?? message(run.error as Error)}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="sm" disabled={!text.trim() || run.isPending}>
          {run.isPending ? "Importing…" : "Import"}
        </Button>
      </div>
    </form>
  );
}

function SkillRow({ skill, agents }: { skill: Skill; agents: Agent[] }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
  const remove = useMutation({
    mutationFn: () => skillsApi.remove(skill.id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: SKILLS });
      await qc.invalidateQueries({ queryKey: AGENTS }); // it leaves their lists
    },
  });
  const owner = agents.find((a) => a.id === skill.agent_id);

  if (mode === "edit")
    return (
      <li aria-label={`Edit ${skill.name}`}>
        <SkillForm
          initial={skill}
          agents={agents}
          submitLabel="Save"
          onCancel={() => setMode("view")}
          onSave={async (body) => {
            await skillsApi.update(skill.id, body);
            await qc.invalidateQueries({ queryKey: SKILLS });
            await qc.invalidateQueries({ queryKey: AGENTS });
            setMode("view");
          }}
        />
      </li>
    );

  return (
    <li className="flex flex-col gap-2 px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate font-mono text-sm text-fg">{skill.name}</p>
          <p className="text-sm text-fg-muted">{skill.description}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Edit ${skill.name}`}
          onClick={() => setMode("edit")}
        >
          <Pencil size={14} aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Delete ${skill.name}`}
          onClick={() => setMode("delete")}
        >
          <Trash2 size={14} aria-hidden />
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge>{skill.agent_id === null ? "shared" : `only ${owner?.name ?? "an agent"}`}</Badge>
        {skill.tags.map((t) => (
          <Badge key={t}>{t}</Badge>
        ))}
        {skill.written_by_task && (
          <Link
            to={`/tasks/${skill.written_by_task}`}
            className="text-xs text-accent hover:underline"
          >
            written by SEED, with your approval
          </Link>
        )}
      </div>
      {mode === "delete" && (
        <div
          role="group"
          aria-label={`Delete ${skill.name}?`}
          className="flex flex-wrap items-center gap-2 rounded-control border border-border bg-surface-2 px-3 py-2 text-xs"
        >
          <span className="flex-1 text-fg">Delete {skill.name}? This cannot be undone.</span>
          <Button size="sm" onClick={() => setMode("view")}>
            Keep
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            Delete
          </Button>
          {remove.isError && (
            <p role="alert" className="w-full text-danger">
              {message(remove.error)}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/** The Skills panel of the Tools & Skills page (D-033). */
export function SkillsPanel() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: SKILLS, queryFn: skillsApi.list, retry: false });
  const agents = useQuery({ queryKey: AGENTS, queryFn: agentsApi.list, retry: false });
  const [open, setOpen] = useState<"none" | "new" | "import">("none");
  const roster = agents.data ?? [];

  return (
    <Panel
      title="Skills"
      action={
        open === "none" && (
          <div className="flex gap-2">
            <Button size="sm" onClick={() => setOpen("import")}>
              <FileUp size={14} aria-hidden /> Import
            </Button>
            <Button size="sm" onClick={() => setOpen("new")}>
              <Plus size={14} aria-hidden /> New skill
            </Button>
          </div>
        )
      }
    >
      <p className="border-b border-border px-4 py-2 text-xs text-fg-muted">
        Procedures SEED follows when a request matches. Each task sees only their names and what
        they are for, and reads one in full when it needs it. Start a message with /name to use one.
      </p>
      {open === "new" && (
        <div role="group" aria-label="New skill" className="border-b border-border">
          <SkillForm
            initial={BLANK}
            agents={roster}
            submitLabel="Create"
            onCancel={() => setOpen("none")}
            onSave={async (body) => {
              await skillsApi.create(body);
              await qc.invalidateQueries({ queryKey: SKILLS });
              setOpen("none");
            }}
          />
        </div>
      )}
      {open === "import" && (
        <div role="group" aria-label="Import a skill" className="border-b border-border">
          <ImportForm agents={roster} onDone={() => setOpen("none")} />
        </div>
      )}
      {list.isPending ? (
        <div className="flex items-center gap-2 px-4 py-6 text-sm text-fg-muted">
          <Spinner /> Loading…
        </div>
      ) : list.isError ? (
        <div className="flex items-start gap-2 px-4 py-4 text-sm text-danger" role="alert">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
          {message(list.error)}
        </div>
      ) : list.data.length === 0 ? (
        open === "none" && (
          <EmptyState icon={Sparkles} title="No skills yet">
            Write one, or import a SKILL.md from Hermes Agent. SEED can also save one when you
            approve it.
          </EmptyState>
        )
      ) : (
        <ul aria-label="Skills" className="divide-y divide-border">
          {list.data.map((s) => (
            <SkillRow key={s.id} skill={s} agents={roster} />
          ))}
        </ul>
      )}
    </Panel>
  );
}
