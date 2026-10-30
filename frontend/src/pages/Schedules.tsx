import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, Pause, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { ApiError, api } from "../lib/api";
import { PROJECTS, projectsApi } from "../lib/projects";
import {
  MAX_EVERY_MINUTES,
  MIN_EVERY_MINUTES,
  SCHEDULES,
  describeTimetable,
  schedulesApi,
} from "../lib/schedules";
import type { Schedule, ScheduleInput } from "../lib/schedules";

const field =
  "rounded-control border border-border bg-surface-1 px-2.5 text-sm text-fg outline-none focus:border-accent";
const tidy = (s: string) => s.split(/\s+/).filter(Boolean).join(" ");
const message = (e: Error) => (e instanceof ApiError ? e.message : "Unexpected error.");
const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

const browserZone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
};
const zones = (): string[] => {
  try {
    return (
      (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.(
        "timeZone",
      ) ?? []
    );
  } catch {
    return [];
  }
};

const blank = (): ScheduleInput => ({
  name: "",
  prompt: "",
  model: "",
  project_id: null,
  kind: "interval",
  every_minutes: 60,
  at_time: null,
  timezone: browserZone(),
  enabled: true,
});

function ScheduleForm({
  initial,
  submitLabel,
  onSave,
  onCancel,
}: {
  initial: ScheduleInput;
  submitLabel: string;
  onSave: (body: ScheduleInput) => Promise<unknown>;
  onCancel: () => void;
}) {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models, retry: false });
  const projects = useQuery({ queryKey: PROJECTS, queryFn: projectsApi.list, retry: false });
  const [draft, setDraft] = useState<ScheduleInput>({
    ...initial,
    at_time: initial.at_time?.slice(0, 5) ?? null,
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<ScheduleInput>) => setDraft((d) => ({ ...d, ...patch }));
  const model = draft.model || models.data?.default_model || "";
  const choices = models.data?.models.map((m) => m.id) ?? [];
  if (model && !choices.includes(model)) choices.push(model);
  const timetableOk =
    draft.kind === "interval"
      ? draft.every_minutes !== null &&
        draft.every_minutes >= MIN_EVERY_MINUTES &&
        draft.every_minutes <= MAX_EVERY_MINUTES
      : Boolean(draft.at_time) && Boolean(draft.timezone.trim());
  const ready = tidy(draft.name) && draft.prompt.trim() && model && timetableOk;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        ...draft,
        name: tidy(draft.name),
        prompt: draft.prompt.trim(),
        model,
        every_minutes: draft.kind === "interval" ? draft.every_minutes : null,
        at_time: draft.kind === "daily" ? draft.at_time : null,
        timezone: draft.kind === "daily" ? draft.timezone.trim() : draft.timezone,
      });
    } catch (err) {
      setError(message(err as Error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 px-4 py-4">
      <label className="flex flex-col gap-1 text-xs text-fg-muted sm:max-w-sm">
        Name
        <input
          value={draft.name}
          maxLength={80}
          onChange={(e) => set({ name: e.target.value })}
          placeholder="Morning summary"
          className={`h-8 ${field}`}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-fg-muted">
        What the task should do
        <textarea
          value={draft.prompt}
          maxLength={20000}
          rows={4}
          onChange={(e) => set({ prompt: e.target.value })}
          placeholder="Summarise what changed in the project since yesterday"
          className={`resize-y py-2 ${field}`}
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-fg-muted">
          Model
          <select
            value={model}
            onChange={(e) => set({ model: e.target.value })}
            className={`h-8 font-mono text-xs ${field}`}
          >
            {choices.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-fg-muted">
          Project
          <select
            value={draft.project_id ?? ""}
            onChange={(e) => set({ project_id: e.target.value || null })}
            className={`h-8 ${field}`}
          >
            <option value="">No project</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-xs text-fg-muted">When</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-fg">
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="kind"
              checked={draft.kind === "interval"}
              onChange={() => set({ kind: "interval" })}
              className="accent-accent"
            />
            Every so often
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="kind"
              checked={draft.kind === "daily"}
              onChange={() => set({ kind: "daily", at_time: draft.at_time ?? "09:00" })}
              className="accent-accent"
            />
            Daily at a time
          </label>
        </div>
        {draft.kind === "interval" ? (
          <label className="flex flex-col gap-1 text-xs text-fg-muted sm:max-w-xs">
            Minutes between runs ({MIN_EVERY_MINUTES} to {MAX_EVERY_MINUTES})
            <input
              type="number"
              inputMode="numeric"
              min={MIN_EVERY_MINUTES}
              max={MAX_EVERY_MINUTES}
              value={draft.every_minutes ?? ""}
              onChange={(e) =>
                set({ every_minutes: e.target.value === "" ? null : Number(e.target.value) })
              }
              className={`h-8 ${field}`}
            />
          </label>
        ) : (
          <div className="grid gap-3 sm:max-w-md sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs text-fg-muted">
              Time
              <input
                type="time"
                value={draft.at_time ?? ""}
                onChange={(e) => set({ at_time: e.target.value || null })}
                className={`h-8 ${field}`}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-fg-muted">
              Time zone
              <input
                list="schedule-zones"
                value={draft.timezone}
                onChange={(e) => set({ timezone: e.target.value })}
                className={`h-8 font-mono text-xs ${field}`}
              />
              <datalist id="schedule-zones">
                {zones().map((z) => (
                  <option key={z} value={z} />
                ))}
              </datalist>
            </label>
          </div>
        )}
      </fieldset>
      <label className="flex items-center gap-2 text-sm text-fg">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => set({ enabled: e.target.checked })}
          className="accent-accent"
        />
        On
      </label>
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

const toInput = (s: Schedule): ScheduleInput => ({
  name: s.name,
  prompt: s.prompt,
  model: s.model,
  project_id: s.project_id,
  kind: s.kind,
  every_minutes: s.every_minutes,
  at_time: s.at_time,
  timezone: s.timezone,
  enabled: s.enabled,
});

function ScheduleRow({ schedule, projectName }: { schedule: Schedule; projectName?: string }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
  const refresh = () => void qc.invalidateQueries({ queryKey: SCHEDULES });
  const remove = useMutation({
    mutationFn: () => schedulesApi.remove(schedule.id),
    onSuccess: refresh,
  });
  const toggle = useMutation({
    mutationFn: () =>
      schedulesApi.update(schedule.id, { ...toInput(schedule), enabled: !schedule.enabled }),
    onSuccess: refresh,
  });
  const run = useMutation({ mutationFn: () => schedulesApi.run(schedule.id), onSuccess: refresh });

  if (mode === "edit")
    return (
      <li aria-label={`Edit ${schedule.name}`}>
        <ScheduleForm
          initial={toInput(schedule)}
          submitLabel="Save"
          onCancel={() => setMode("view")}
          onSave={async (body) => {
            await schedulesApi.update(schedule.id, body);
            await qc.invalidateQueries({ queryKey: SCHEDULES });
            setMode("view");
          }}
        />
      </li>
    );

  const last =
    schedule.last_run_at === null
      ? "Has not run yet"
      : `Last run ${when(schedule.last_run_at)}${
          schedule.last_outcome === "skipped_busy" ? ", skipped: the last task was still going" : ""
        }`;
  const error = [toggle, run, remove].find((m) => m.isError)?.error;
  return (
    <li className="flex flex-col gap-2 px-4 py-3">
      <div className="flex items-start gap-1">
        <div className="min-w-0 flex-1">
          <p className="break-words text-sm font-medium text-fg">{schedule.name}</p>
          <p className="text-sm text-fg-muted">{describeTimetable(schedule)}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Run ${schedule.name} now`}
          disabled={run.isPending}
          onClick={() => run.mutate()}
        >
          <Play size={14} aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`${schedule.enabled ? "Pause" : "Resume"} ${schedule.name}`}
          disabled={toggle.isPending}
          onClick={() => toggle.mutate()}
        >
          {schedule.enabled ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Edit ${schedule.name}`}
          onClick={() => setMode("edit")}
        >
          <Pencil size={14} aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Delete ${schedule.name}`}
          onClick={() => setMode("delete")}
        >
          <Trash2 size={14} aria-hidden />
        </Button>
      </div>
      <p className="line-clamp-2 break-words text-xs text-fg-muted">{schedule.prompt}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={schedule.enabled ? "accent" : "neutral"}>
          {schedule.enabled ? "on" : "paused"}
        </Badge>
        <Badge>{schedule.model}</Badge>
        {projectName && <Badge>{projectName}</Badge>}
        <span className="text-xs text-fg-muted">
          {schedule.next_run_at ? `Next run ${when(schedule.next_run_at)}` : "Paused"} · {last}
        </span>
        {schedule.last_task_id && (
          <Link
            to={`/tasks/${schedule.last_task_id}`}
            className="text-xs text-accent hover:underline"
          >
            Last task
          </Link>
        )}
      </div>
      {run.isSuccess && (
        <p role="status" className="text-xs text-fg-muted">
          Started a task.{" "}
          <Link to={`/tasks/${run.data.task_id}`} className="text-accent hover:underline">
            Open it
          </Link>
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {message(error)}
        </p>
      )}
      {mode === "delete" && (
        <div
          role="group"
          aria-label={`Delete ${schedule.name}?`}
          className="flex flex-wrap items-center gap-2 rounded-control border border-border bg-surface-2 px-3 py-2 text-xs"
        >
          <span className="flex-1 text-fg">
            Delete {schedule.name}? Tasks it already started are kept.
          </span>
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
        </div>
      )}
    </li>
  );
}

export function SchedulesPage() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: SCHEDULES, queryFn: schedulesApi.list, retry: false });
  const projects = useQuery({ queryKey: PROJECTS, queryFn: projectsApi.list, retry: false });
  const [adding, setAdding] = useState(false);
  const projectName = (id: string | null) => projects.data?.find((p) => p.id === id)?.name;

  return (
    <>
      <PageHeader
        title="Schedules"
        description="Tasks that start on their own, every so often or at a time each day."
      />
      <p className="mb-4 rounded-control border border-dashed border-border px-3 py-2 text-xs text-fg-muted">
        A schedule starts a task like any other, so it shows in Tasks and may wait for your
        approval. If its last task is still going when the next run is due, that run is skipped.
      </p>
      <Panel
        title="Your schedules"
        action={
          !adding && (
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus size={14} aria-hidden /> New schedule
            </Button>
          )
        }
      >
        {adding && (
          <div aria-label="New schedule" role="group" className="border-b border-border">
            <ScheduleForm
              initial={blank()}
              submitLabel="Create"
              onCancel={() => setAdding(false)}
              onSave={async (body) => {
                await schedulesApi.create(body);
                await qc.invalidateQueries({ queryKey: SCHEDULES });
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
            <EmptyState icon={CalendarClock} title="No schedules yet">
              Say what a task should do and when, and the workers start it for you.
            </EmptyState>
          )
        ) : (
          <ul aria-label="Schedules" className="divide-y divide-border">
            {list.data.map((s) => (
              <ScheduleRow key={s.id} schedule={s} projectName={projectName(s.project_id)} />
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}
