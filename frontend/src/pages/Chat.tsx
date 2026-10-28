import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUp,
  CheckCircle2,
  ChevronRight,
  Cpu,
  MessageSquare,
  Square,
  Wrench,
  XCircle,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { cn } from "../components/ui/cn";
import { ApiError, api } from "../lib/api";
import { streamRun } from "../lib/runs";
import type { RunEvent } from "../lib/runs";

type ToolActivity = {
  id: string;
  name: string;
  args: unknown;
  ok?: boolean;
  error?: string;
  durationMs?: number;
};

type Turn = {
  prompt: string;
  text: string;
  tools: ToolActivity[];
  status: "running" | "done" | "failed";
  termination?: string;
  error?: string;
  steps?: number;
  tokens?: { input: number; output: number };
};

function applyEvent(turn: Turn, e: RunEvent): Turn {
  const d = e.data;
  switch (e.type) {
    case "text_delta":
      return { ...turn, text: turn.text + String(d.text ?? "") };
    case "step_started":
      // Each step's text replaces the previous step's: the final step carries the answer.
      return Number(d.step) > 1 ? { ...turn, text: "" } : turn;
    case "tool_call":
      return {
        ...turn,
        tools: [...turn.tools, { id: String(d.id), name: String(d.name), args: d.arguments }],
      };
    case "tool_result":
      return {
        ...turn,
        tools: turn.tools.map((t) =>
          t.id === String(d.id) && t.ok === undefined
            ? {
                ...t,
                ok: Boolean(d.ok),
                error: d.ok ? undefined : String(d.error ?? d.error_kind ?? "failed"),
                durationMs: typeof d.duration_ms === "number" ? d.duration_ms : undefined,
              }
            : t,
        ),
      };
    case "run_finished": {
      const usage = d.usage as { input_tokens: number; output_tokens: number } | undefined;
      return {
        ...turn,
        status: d.termination === "completed" ? "done" : "failed",
        termination: String(d.termination),
        error: d.error ? String(d.error) : undefined,
        steps: Number(d.steps),
        tokens: usage ? { input: usage.input_tokens, output: usage.output_tokens } : undefined,
      };
    }
    default:
      return turn;
  }
}

function ToolList({ tools }: { tools: ToolActivity[] }) {
  const [open, setOpen] = useState(false);
  if (!tools.length) return null;
  return (
    <div className="rounded-control border border-border bg-surface-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex h-8 w-full items-center gap-2 px-2.5 text-xs text-fg-muted hover:text-fg"
      >
        <ChevronRight
          size={14}
          className={cn("transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <Wrench size={13} aria-hidden />
        Used {tools.length} tool{tools.length === 1 ? "" : "s"}
        {tools.some((t) => t.ok === false) && <Badge tone="warning">some failed</Badge>}
      </button>
      {open && (
        <ul className="divide-y divide-border border-t border-border">
          {tools.map((t) => (
            <li key={t.id} className="px-3 py-2 text-xs">
              <div className="flex items-center gap-2">
                {t.ok === undefined ? (
                  <Spinner label="Running tool" />
                ) : t.ok ? (
                  <CheckCircle2 size={13} className="text-accent" aria-label="Succeeded" />
                ) : (
                  <XCircle size={13} className="text-danger" aria-label="Failed" />
                )}
                <span className="font-mono font-medium text-fg">{t.name}</span>
                {t.durationMs !== undefined && (
                  <span className="ml-auto font-mono text-fg-subtle">{t.durationMs} ms</span>
                )}
              </div>
              <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap break-all font-mono text-2xs text-fg-muted">
                {JSON.stringify(t.args)}
              </pre>
              {t.error && <p className="mt-1 text-danger">{t.error}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="ml-auto max-w-[80%] rounded-panel bg-surface-3 px-3.5 py-2.5 text-sm whitespace-pre-wrap text-fg">
        {turn.prompt}
      </div>
      <div className="flex flex-col gap-2">
        <ToolList tools={turn.tools} />
        {turn.text && (
          <div className="text-sm leading-6 whitespace-pre-wrap text-fg">{turn.text}</div>
        )}
        {turn.status === "running" && !turn.text && (
          <div className="flex items-center gap-2 text-xs text-fg-muted">
            <Spinner /> Working…
          </div>
        )}
        {turn.status === "failed" && (
          <p role="alert" className="flex items-start gap-2 text-xs text-danger">
            <AlertTriangle size={14} className="mt-px shrink-0" aria-hidden />
            {turn.error ?? `Stopped: ${turn.termination ?? "unknown"}`}
          </p>
        )}
        {turn.steps !== undefined && (
          <p className="font-mono text-2xs text-fg-subtle">
            {turn.termination} · {turn.steps} step{turn.steps === 1 ? "" : "s"}
            {turn.tokens && ` · ${turn.tokens.input} in / ${turn.tokens.output} out tokens`}
          </p>
        )}
      </div>
    </div>
  );
}

export function ChatPage() {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models, retry: false });
  const [model, setModel] = useState<string>("");
  const [prompt, setPrompt] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const running = turns.at(-1)?.status === "running";
  const selected = model || models.data?.default_model || models.data?.models[0]?.id || "";

  // Braces matter: Chromium's scrollIntoView returns a Promise, and an effect that
  // returns a non-function crashes React on cleanup.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns]);
  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const update = (fn: (t: Turn) => Turn) =>
    setTurns((ts) => (ts.length ? [...ts.slice(0, -1), fn(ts[ts.length - 1]!)] : ts));

  const send = async (e?: FormEvent) => {
    e?.preventDefault();
    const text = prompt.trim();
    if (!text || running || !selected) return;
    const history = turns
      .filter((t) => t.status === "done")
      .flatMap((t) => [
        { role: "user" as const, content: t.prompt },
        { role: "assistant" as const, content: t.text },
      ]);
    setPrompt("");
    setTurns((ts) => [...ts, { prompt: text, text: "", tools: [], status: "running" }]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamRun({ model: selected, prompt: text, history }, controller.signal, (ev) =>
        update((t) => applyEvent(t, ev)),
      );
      update((t) =>
        t.status === "running"
          ? { ...t, status: "failed", error: "The stream ended before the run finished." }
          : t,
      );
    } catch (err) {
      const message = controller.signal.aborted
        ? "Stopped."
        : err instanceof ApiError
          ? err.message
          : "Unexpected error.";
      update((t) => ({ ...t, status: "failed", termination: "stopped", error: message }));
    } finally {
      abortRef.current = null;
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  };

  if (models.isError) {
    const err = models.error;
    const notConfigured = err instanceof ApiError && err.code === "provider_not_configured";
    return (
      <Panel>
        <EmptyState
          icon={notConfigured ? Cpu : AlertTriangle}
          title={notConfigured ? "No model provider configured" : "Models unavailable"}
        >
          {err.message}
        </EmptyState>
      </Panel>
    );
  }

  return (
    <div className="flex h-[calc(100dvh-3rem-3rem)] min-h-[420px] flex-col sm:h-[calc(100dvh-3rem-4rem)]">
      <div className="flex flex-wrap items-center gap-3 pb-4">
        <h1 className="text-[22px] leading-7 font-semibold tracking-[-0.015em]">Chat</h1>
        <Badge tone="warning">Not saved · runs stop if you leave</Badge>
        <label className="ml-auto flex items-center gap-2 text-xs text-fg-muted">
          Model
          <select
            value={selected}
            onChange={(e) => setModel(e.target.value)}
            disabled={models.isPending || running}
            className="h-8 max-w-56 rounded-control border border-border bg-surface-1 px-2 font-mono text-xs text-fg"
          >
            {models.isPending && <option>Loading…</option>}
            {models.data?.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto rounded-panel border border-border bg-surface-1">
        {turns.length === 0 ? (
          <EmptyState icon={MessageSquare} title="Ask SEED to do something">
            SEED can answer directly or use its workspace tools to create, list and read files.
            Every tool call is shown with its arguments and result.
          </EmptyState>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-5 sm:px-6">
            {turns.map((t, i) => (
              <TurnView key={i} turn={t} />
            ))}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <form onSubmit={send} className="mt-3 flex items-end gap-2">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          maxLength={20000}
          placeholder="Describe what you want done…  (Enter to send, Shift+Enter for a new line)"
          aria-label="Message"
          className="min-h-[52px] flex-1 resize-none rounded-panel border border-border bg-surface-1 px-3.5 py-3 text-sm text-fg outline-none placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-ring"
        />
        {running ? (
          <Button
            variant="secondary"
            size="icon"
            className="h-[52px] w-[52px]"
            onClick={() => abortRef.current?.abort()}
            aria-label="Stop run"
          >
            <Square size={16} />
          </Button>
        ) : (
          <Button
            type="submit"
            variant="primary"
            size="icon"
            className="h-[52px] w-[52px]"
            disabled={!prompt.trim() || !selected}
            aria-label="Send"
          >
            <ArrowUp size={18} />
          </Button>
        )}
      </form>
    </div>
  );
}
