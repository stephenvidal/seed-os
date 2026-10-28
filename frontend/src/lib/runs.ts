/** Client for POST /api/v1/runs: streams Server-Sent Events from an agent run. */
import { ApiError, csrfHeaders } from "./api";

export type RunEventType =
  | "run_id"
  | "run_started"
  | "step_started"
  | "text_delta"
  | "tool_call"
  | "tool_result"
  | "step_completed"
  | "provider_retry"
  | "run_finished";

export type RunEvent = { type: RunEventType; data: Record<string, unknown> };

export type RunRequest = {
  model: string;
  prompt: string;
  history: { role: "user" | "assistant"; content: string }[];
};

/** Splits an SSE buffer into complete events; returns the unconsumed remainder. */
export function parseSse(buffer: string): { events: RunEvent[]; rest: string } {
  const events: RunEvent[] = [];
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let type: string | null = null;
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) type = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (type && data) events.push({ type: type as RunEventType, data: JSON.parse(data) });
  }
  return { events, rest };
}

export async function streamRun(
  body: RunRequest,
  signal: AbortSignal,
  onEvent: (e: RunEvent) => void,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/v1/runs", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (signal.aborted) throw e;
    throw new ApiError(0, "network_unreachable", "Cannot reach the SEED API.");
  }
  if (!res.ok || !res.body) {
    const err = (await res.json().catch(() => null)) as {
      error?: { code?: string; message?: string };
    } | null;
    throw new ApiError(
      res.status,
      err?.error?.code ?? "http_error",
      err?.error?.message ?? `HTTP ${res.status}`,
    );
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    const { events, rest } = parseSse(buffer);
    buffer = rest;
    events.forEach(onEvent);
  }
}
