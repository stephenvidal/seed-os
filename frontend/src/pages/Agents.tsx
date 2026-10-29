import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { AGENTS, AGENT_TOOLS, agentsApi } from "../lib/agents";
import type { Agent, AgentInput, AgentTool } from "../lib/agents";
import { ApiError, api } from "../lib/api";

const field =
  "rounded-control border border-border bg-surface-1 px-2.5 text-sm text-fg outline-none focus:border-accent";
const tidy = (s: string) => s.split(/\s+/).filter(Boolean).join(" ");
const message = (e: Error) => (e instanceof ApiError ? e.message : "Unexpected error.");

const BLANK: AgentInput = { name: "", description: "", instructions: "", model: null, tools: [] };

/** Create or change an agent: every field is sent, as the API replaces the whole definition. */
function AgentForm({
  initial,
  submitLabel,
  onSave,
  onCancel,
}: {
  initial: AgentInput;
  submitLabel: string;
  onSave: (body: AgentInput) => Promise<unknown>;
  onCancel: () => void;
}) {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models, retry: false });
  const [draft, setDraft] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<AgentInput>) => setDraft((d) => ({ ...d, ...patch }));
  const toggle = (tool: AgentTool) =>
    set({
      tools: draft.tools.includes(tool)
        ? draft.tools.filter((t) => t !== tool)
        : [...draft.tools, tool],
    });
  const ready = tidy(draft.name) && tidy(draft.description);
  // A model the agent names that the provider does not list still shows.
  const choices = models.data?.models.map((m) => m.id) ?? [];
  if (draft.model && !choices.includes(draft.model)) choices.push(draft.model);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        name: tidy(draft.name),
        description: tidy(draft.description),
        instructions: draft.instructions,
        model: draft.model,
        tools: draft.tools,
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
            maxLength={40}
            onChange={(e) => set({ name: e.target.value })}
            placeholder="Researcher"
            className={`h-8 ${field}`}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-fg-muted">
          What it is for
          <input
            value={draft.description}
            maxLength={500}
            onChange={(e) => set({ description: e.target.value })}
            placeholder="Finds and reads sources, and reports what they say"
            className={`h-8 ${field}`}
          />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-xs text-fg-muted">
        Instructions
        <textarea
          value={draft.instructions}
          maxLength={20000}
          rows={4}
          onChange={(e) => set({ instructions: e.target.value })}
          placeholder="How this agent should work, and what to report back"
          className={`resize-y py-2 ${field}`}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-fg-muted sm:max-w-xs">
        Model
        <select
          value={draft.model ?? ""}
          onChange={(e) => set({ model: e.target.value || null })}
          className={`h-8 font-mono text-xs ${field}`}
        >
          <option value="">Same as the task that delegates</option>
          {choices.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-xs text-fg-muted">Tools it may use</legend>
        {AGENT_TOOLS.map((t) => (
          <label key={t.name} className="flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={draft.tools.includes(t.name)}
              onChange={() => toggle(t.name)}
              className="accent-accent"
            />
            {t.label}
            {"note" in t && <span className="text-xs text-fg-muted">({t.note})</span>}
          </label>
        ))}
      </fieldset>
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

function AgentRow({ agent }: { agent: Agent }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
  const remove = useMutation({
    mutationFn: () => agentsApi.remove(agent.id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: AGENTS }),
  });

  if (mode === "edit")
    return (
      <li aria-label={`Edit ${agent.name}`}>
        <AgentForm
          initial={agent}
          submitLabel="Save"
          onCancel={() => setMode("view")}
          onSave={async (body) => {
            await agentsApi.update(agent.id, body);
            await qc.invalidateQueries({ queryKey: AGENTS });
            setMode("view");
          }}
        />
      </li>
    );

  const tools = AGENT_TOOLS.filter((t) => agent.tools.includes(t.name));
  return (
    <li className="flex flex-col gap-2 px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-fg">{agent.name}</p>
          <p className="text-sm text-fg-muted">{agent.description}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Edit ${agent.name}`}
          onClick={() => setMode("edit")}
        >
          <Pencil size={14} aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Delete ${agent.name}`}
          onClick={() => setMode("delete")}
        >
          <Trash2 size={14} aria-hidden />
        </Button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Badge>{agent.model ?? "task's model"}</Badge>
        {tools.length === 0 ? (
          <Badge>no tools</Badge>
        ) : (
          tools.map((t) => <Badge key={t.name}>{t.label}</Badge>)
        )}
        {agent.instructions && <Badge>instructions</Badge>}
      </div>
      {mode === "delete" && (
        <div
          role="group"
          aria-label={`Delete ${agent.name}?`}
          className="flex flex-wrap items-center gap-2 rounded-control border border-border bg-surface-2 px-3 py-2 text-xs"
        >
          <span className="flex-1 text-fg">Delete {agent.name}? This cannot be undone.</span>
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

export function AgentsPage() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: AGENTS, queryFn: agentsApi.list, retry: false });
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PageHeader
        title="Agents"
        description="Specialists SEED can hand part of a job to. You talk to SEED; it decides when one helps."
      />
      <p className="mb-4 rounded-control border border-dashed border-border px-3 py-2 text-xs text-fg-muted">
        When one of these clearly helps, SEED hands it part of the job as a task of its own, with
        only the tools ticked here. Changes apply to work handed over afterwards.
      </p>
      <Panel
        title="Your agents"
        action={
          !adding && (
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus size={14} aria-hidden /> New agent
            </Button>
          )
        }
      >
        {adding && (
          <div aria-label="New agent" role="group" className="border-b border-border">
            <AgentForm
              initial={BLANK}
              submitLabel="Create"
              onCancel={() => setAdding(false)}
              onSave={async (body) => {
                await agentsApi.create(body);
                await qc.invalidateQueries({ queryKey: AGENTS });
                setAdding(false);
              }}
            />
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
          !adding && (
            <EmptyState icon={Bot} title="No agents yet">
              Give each one a name, say what it is for, and choose the tools it may use. Each
              delegated job runs as its own task with only those tools.
            </EmptyState>
          )
        ) : (
          <ul aria-label="Agents" className="divide-y divide-border">
            {list.data.map((a) => (
              <AgentRow key={a.id} agent={a} />
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}
