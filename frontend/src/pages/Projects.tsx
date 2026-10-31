import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, FolderKanban, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { ApiError } from "../lib/api";
import { chatApi } from "../lib/chat";
import { formatBytes } from "../lib/format";
import {
  DOCUMENT_TYPES,
  MAX_DOCUMENT_CHARS,
  PROJECTS,
  documentsKey,
  knowledgeApi,
  memoryApi,
  memoryKey,
  projectKey,
  projectsApi,
} from "../lib/projects";
import type { Project } from "../lib/projects";
import { studioApi } from "../lib/studio";
import { tasksApi } from "../lib/tasks";
import { StateBadge } from "../components/tasks/StateBadge";
import { MemoryNotes } from "../components/MemoryNotes";

const MAX_INSTRUCTIONS = 20_000;
const field =
  "rounded-control border border-border bg-surface-1 px-2.5 text-sm text-fg outline-none focus:border-accent";
const tidy = (name: string) => name.split(/\s+/).filter(Boolean).join(" ");

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

function NewProject() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => projectsApi.create({ name: tidy(name) }),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: PROJECTS });
      navigate(`/projects/${p.id}`);
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (tidy(name)) create.mutate();
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2 px-4 py-3">
      <input
        aria-label="New project name"
        placeholder="New project name"
        value={name}
        maxLength={80}
        onChange={(e) => setName(e.target.value)}
        className={`h-8 min-w-0 flex-1 ${field}`}
      />
      <Button type="submit" variant="primary" size="sm" disabled={create.isPending || !tidy(name)}>
        <Plus size={14} aria-hidden /> Create
      </Button>
      {create.isError && (
        <p role="alert" className="w-full text-xs text-danger">
          {create.error instanceof ApiError ? create.error.message : "Unexpected error."}
        </p>
      )}
    </form>
  );
}

export function ProjectsPage() {
  const list = useQuery({ queryKey: PROJECTS, queryFn: projectsApi.list, retry: false });
  return (
    <>
      <PageHeader
        title="Projects"
        description="Group chats under one name, with instructions SEED follows in every one of them."
      />
      <Panel title="Your projects">
        <NewProject />
        {list.isPending ? (
          <Loading />
        ) : list.isError ? (
          <Failure error={list.error} />
        ) : list.data.length === 0 ? (
          <EmptyState icon={FolderKanban} title="No projects yet">
            Create one, give it instructions, and start chats in it. Its chats and the files they
            make are listed together.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {list.data.map((p) => (
              <li key={p.id}>
                <Link
                  to={`/projects/${p.id}`}
                  className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-2"
                >
                  <span className="min-w-0 flex-1 truncate text-sm text-fg">{p.name}</span>
                  {p.proposed_memories > 0 && (
                    <Badge tone="accent">{p.proposed_memories} to review</Badge>
                  )}
                  {p.instructions && <Badge>instructions</Badge>}
                  <span className="shrink-0 text-xs text-fg-muted tabular-nums">
                    {p.conversations === 1 ? "1 chat" : `${p.conversations} chats`}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}

function Header({ project }: { project: Project }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"view" | "rename" | "delete">("view");
  const [name, setName] = useState(project.name);
  const rename = useMutation({
    mutationFn: () => projectsApi.update(project.id, { name: tidy(name) }),
    onSuccess: (p) => {
      qc.setQueryData(projectKey(p.id), p);
      void qc.invalidateQueries({ queryKey: PROJECTS });
      setMode("view");
    },
  });
  const remove = useMutation({
    mutationFn: () => projectsApi.remove(project.id),
    onSuccess: () => {
      qc.removeQueries({ queryKey: projectKey(project.id) });
      void qc.invalidateQueries({ queryKey: PROJECTS });
      void qc.invalidateQueries({ queryKey: ["conversations"] });
      navigate("/projects");
    },
  });
  const failure = rename.error ?? remove.error;

  function save(e: FormEvent) {
    e.preventDefault();
    if (!tidy(name)) return;
    if (tidy(name) === project.name) setMode("view");
    else rename.mutate();
  }

  return (
    <div className="pb-6">
      <Link
        to="/projects"
        className="mb-2 inline-flex items-center gap-1 text-xs text-fg-muted hover:text-fg"
      >
        <ArrowLeft size={13} aria-hidden /> All projects
      </Link>
      {mode === "rename" ? (
        <form onSubmit={save} className="flex items-center gap-2">
          <input
            aria-label="Project name"
            value={name}
            maxLength={80}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setMode("view");
            }}
            className={`h-9 min-w-0 flex-1 ${field}`}
          />
          <Button type="submit" variant="primary" size="sm" disabled={rename.isPending}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setMode("view")}>
            Cancel
          </Button>
        </form>
      ) : (
        <div className="flex items-center gap-1">
          <h1 className="min-w-0 flex-1 truncate text-[22px] leading-7 font-semibold tracking-[-0.015em] text-fg">
            {project.name}
          </h1>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Rename project"
            onClick={() => {
              setName(project.name);
              rename.reset();
              setMode("rename");
            }}
          >
            <Pencil size={14} aria-hidden />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Delete project"
            onClick={() => {
              remove.reset();
              setMode("delete");
            }}
          >
            <Trash2 size={14} aria-hidden />
          </Button>
        </div>
      )}
      {mode === "delete" && (
        <div
          role="alertdialog"
          aria-label="Delete project"
          className="mt-2 flex flex-wrap items-center gap-2 rounded-control border border-danger bg-danger-soft px-3 py-2 text-xs text-fg"
        >
          <p className="min-w-0 flex-1">
            Delete this project? Its{" "}
            {project.conversations === 1 ? "chat is" : `${project.conversations} chats are`} kept
            and leave the project; its instructions are deleted.
          </p>
          <Button
            size="sm"
            className="border-danger text-danger"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setMode("view")}>
            Keep
          </Button>
        </div>
      )}
      {failure && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {failure instanceof ApiError ? failure.message : "Unexpected error."}
        </p>
      )}
    </div>
  );
}

function Instructions({ project }: { project: Project }) {
  const qc = useQueryClient();
  const [text, setText] = useState(project.instructions);
  const save = useMutation({
    mutationFn: () => projectsApi.update(project.id, { instructions: text }),
    onSuccess: (p) => {
      qc.setQueryData(projectKey(p.id), p);
      void qc.invalidateQueries({ queryKey: PROJECTS });
      setText(p.instructions);
    },
  });
  const changed = text.trim() !== project.instructions;
  return (
    <Panel title="Instructions">
      <form
        className="flex flex-col gap-2 px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <textarea
          aria-label="Project instructions"
          aria-describedby="instructions-help"
          value={text}
          maxLength={MAX_INSTRUCTIONS}
          rows={6}
          placeholder="For example: answer in French; the site uses plain HTML and CSS."
          onChange={(e) => setText(e.target.value)}
          className={`min-h-28 resize-y py-2 ${field}`}
        />
        <div className="flex flex-wrap items-center gap-2">
          <p id="instructions-help" className="min-w-0 flex-1 text-xs text-fg-muted">
            Sent to the model with every message in this project. A change applies from the next
            message.
          </p>
          {save.isSuccess && !changed && <span className="text-xs text-fg-muted">Saved</span>}
          <Button type="submit" variant="primary" size="sm" disabled={!changed || save.isPending}>
            Save
          </Button>
        </div>
        {save.isError && (
          <p role="alert" className="text-xs text-danger">
            {save.error instanceof ApiError ? save.error.message : "Unexpected error."}
          </p>
        )}
      </form>
    </Panel>
  );
}

function Knowledge({ project }: { project: Project }) {
  const qc = useQueryClient();
  const docs = useQuery({
    queryKey: documentsKey(project.id),
    queryFn: () => knowledgeApi.list(project.id),
    retry: false,
  });
  const [problem, setProblem] = useState<string | null>(null);
  const changed = () => {
    void qc.invalidateQueries({ queryKey: documentsKey(project.id) });
    void qc.invalidateQueries({ queryKey: PROJECTS });
  };
  const add = useMutation({
    mutationFn: async (file: File) => {
      const text = await file.text();
      if (text.length > MAX_DOCUMENT_CHARS)
        throw new Error(`${file.name} is too long (at most 256 KiB of text).`);
      return knowledgeApi.add(project.id, file.name, text);
    },
    onSuccess: changed,
    onError: (e) => setProblem(e instanceof Error ? e.message : "Unexpected error."),
  });
  const remove = useMutation({
    mutationFn: (id: string) => knowledgeApi.remove(project.id, id),
    onSuccess: changed,
    onError: (e) => setProblem(e instanceof Error ? e.message : "Unexpected error."),
  });

  return (
    <Panel title="Knowledge">
      <p className="px-4 pt-3 text-xs text-fg-muted">
        Text documents SEED can search in this project&apos;s chats ({DOCUMENT_TYPES.join(", ")}; up
        to 256 KiB each).
      </p>
      {docs.isPending ? (
        <Loading />
      ) : docs.isError ? (
        <Failure error={docs.error} />
      ) : docs.data.length === 0 ? (
        <p className="px-4 pt-3 text-sm text-fg-muted">No documents yet.</p>
      ) : (
        <ul aria-label="Documents" className="mt-3 divide-y divide-border border-t border-border">
          {docs.data.map((d) => (
            <li key={d.id} className="flex items-center gap-3 px-4 py-2">
              <span className="min-w-0 flex-1 truncate font-mono text-sm text-fg">{d.name}</span>
              <span className="shrink-0 text-xs text-fg-muted tabular-nums">
                {d.chars.toLocaleString()} characters ·{" "}
                {d.chunks === 1 ? "1 passage" : `${d.chunks} passages`}
              </span>
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Delete ${d.name}`}
                disabled={remove.isPending}
                onClick={() => {
                  setProblem(null);
                  remove.mutate(d.id);
                }}
              >
                <Trash2 size={14} aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
        <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-control border border-border px-3 text-xs font-medium text-fg hover:bg-surface-2 focus-within:border-accent">
          <Plus size={14} aria-hidden />
          {add.isPending ? "Adding…" : "Add documents"}
          <input
            type="file"
            multiple
            accept={DOCUMENT_TYPES.join(",")}
            className="sr-only"
            disabled={add.isPending}
            onChange={async (e) => {
              const files = [...(e.target.files ?? [])];
              e.target.value = "";
              setProblem(null);
              for (const f of files) await add.mutateAsync(f).catch(() => undefined);
            }}
          />
        </label>
        {problem && (
          <p role="alert" className="w-full text-xs text-danger">
            {problem}
          </p>
        )}
      </div>
    </Panel>
  );
}

function MemoryPanel({ project }: { project: Project }) {
  const qc = useQueryClient();
  return (
    <MemoryNotes
      title="Memory"
      intro="Notes SEED is given in every chat of this project. SEED can propose notes; they are used only after you approve them."
      placeholder="Add a note, for example: the site targets mobile first"
      queryKey={memoryKey(project.id)}
      api={{
        list: () => memoryApi.list(project.id),
        add: (content) => memoryApi.add(project.id, content),
        update: (id, body) => memoryApi.update(project.id, id, body),
        remove: (id) => memoryApi.remove(project.id, id),
      }}
      onChanged={() => {
        void qc.invalidateQueries({ queryKey: projectKey(project.id) });
        void qc.invalidateQueries({ queryKey: PROJECTS });
      }}
    />
  );
}

function Chats({ project }: { project: Project }) {
  const chats = useQuery({
    queryKey: ["conversations", "project", project.id],
    queryFn: () => chatApi.inProject(project.id),
    retry: false,
  });
  return (
    <Panel
      title="Chats"
      action={
        <Link
          to={`/chat?project=${project.id}`}
          className="flex items-center gap-1 text-xs text-accent hover:underline"
        >
          <Plus size={13} aria-hidden /> New chat
        </Link>
      }
    >
      {chats.isPending ? (
        <Loading />
      ) : chats.isError ? (
        <Failure error={chats.error} />
      ) : chats.data.length === 0 ? (
        <p className="px-4 py-4 text-sm text-fg-muted">
          No chats yet. Start one here, or move a chat in from its header in Chat.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {chats.data.map((c) => (
            <li key={c.id}>
              <Link
                to={`/chat/${c.id}`}
                className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-2"
              >
                <span className="min-w-0 flex-1 truncate text-sm text-fg">{c.title}</span>
                <span className="shrink-0 text-xs text-fg-muted tabular-nums">
                  {c.turns === 1 ? "1 message" : `${c.turns} messages`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** Tasks started in the project outside a chat (D-023). */
function Tasks({ project }: { project: Project }) {
  const tasks = useQuery({
    queryKey: ["tasks", "project", project.id],
    queryFn: () => tasksApi.inProject(project.id),
    retry: false,
  });
  return (
    <Panel
      title="Tasks"
      action={
        <Link
          to={`/tasks?project=${project.id}`}
          className="flex items-center gap-1 text-xs text-accent hover:underline"
        >
          <Plus size={13} aria-hidden /> New task
        </Link>
      }
    >
      {tasks.isPending ? (
        <Loading />
      ) : tasks.isError ? (
        <Failure error={tasks.error} />
      ) : tasks.data.length === 0 ? (
        <p className="px-4 py-4 text-sm text-fg-muted">
          No tasks yet. A task started here runs in the background with the project&apos;s
          instructions, memory and knowledge.
        </p>
      ) : (
        <ul aria-label="Project tasks" className="divide-y divide-border">
          {tasks.data.map((t) => (
            <li key={t.id}>
              <Link
                to={`/tasks/${t.id}`}
                className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-2"
              >
                <span className="min-w-0 flex-1 truncate text-sm text-fg">{t.title}</span>
                <StateBadge task={t} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Files({ project }: { project: Project }) {
  const files = useQuery({
    queryKey: ["artifacts", "project", project.id],
    queryFn: () => studioApi.inProject(project.id),
    retry: false,
  });
  return (
    <Panel title="Files">
      {files.isPending ? (
        <Loading />
      ) : files.isError ? (
        <Failure error={files.error} />
      ) : files.data.length === 0 ? (
        <p className="px-4 py-4 text-sm text-fg-muted">
          No saved files yet. Files the project&apos;s chats make appear here.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {files.data.map((a) => (
            <li key={a.id}>
              <Link
                to={`/studio/${a.id}`}
                className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-2"
              >
                <span className="min-w-0 flex-1 truncate font-mono text-sm text-fg">{a.path}</span>
                {a.latest.deleted && <Badge tone="warning">deleted</Badge>}
                <span className="hidden shrink-0 truncate text-xs text-fg-muted sm:inline">
                  {a.source_title}
                </span>
                <span className="shrink-0 text-xs text-fg-muted tabular-nums">
                  {formatBytes(a.latest.size)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function ProjectPage() {
  const { id = "" } = useParams();
  const project = useQuery({
    queryKey: projectKey(id),
    queryFn: () => projectsApi.get(id),
    retry: false,
  });
  if (project.isPending)
    return (
      <Panel>
        <Loading />
      </Panel>
    );
  if (project.isError)
    return (
      <>
        <Link
          to="/projects"
          className="mb-4 inline-flex items-center gap-1 text-xs text-fg-muted hover:text-fg"
        >
          <ArrowLeft size={13} aria-hidden /> All projects
        </Link>
        <Panel>
          <Failure error={project.error} />
        </Panel>
      </>
    );
  return (
    <>
      <Header key={project.data.name} project={project.data} />
      <div className="flex flex-col gap-4">
        <Instructions project={project.data} />
        <MemoryPanel project={project.data} />
        <Knowledge project={project.data} />
        <div className="grid gap-4 lg:grid-cols-2">
          <Chats project={project.data} />
          <Tasks project={project.data} />
          <Files project={project.data} />
        </div>
      </div>
    </>
  );
}
