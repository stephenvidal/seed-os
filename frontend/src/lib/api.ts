/** Typed client for the SEED API. Every failure surfaces as an ApiError. */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * The session's CSRF token, which the server sets in a readable cookie at sign-in.
 * Every request that changes state must echo it in X-CSRF-Token.
 */
export function csrfHeaders(): Record<string, string> {
  const match = /(?:^|;\s*)seed_csrf=([^;]+)/.exec(document.cookie);
  return match?.[1] ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      credentials: "same-origin",
      ...init,
      headers: { "Content-Type": "application/json", ...csrfHeaders(), ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "network_unreachable", "Cannot reach the SEED API.");
  }
  if (res.status === 204) return undefined as T;
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (body as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `HTTP ${res.status}`);
  }
  return body as T;
}

export type Me = { username: string; role: string };

export type SystemInfo = {
  version: string;
  python: string;
  platform: string;
  uptime_seconds: number;
  cpu_count: number;
  load_average: [number, number, number] | null;
  memory_total_bytes: number | null;
  memory_available_bytes: number | null;
  process_rss_bytes: number | null;
};

export type ModelInfo = { id: string; provider: string; size_bytes: number | null };
export type ModelsResponse = {
  provider: string;
  default_model: string | null;
  models: ModelInfo[];
};

export const api = {
  me: () => request<Me>("/api/v1/auth/me"),
  login: (username: string, password: string) =>
    request<Me>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>("/api/v1/auth/logout", { method: "POST" }),
  system: () => request<SystemInfo>("/api/v1/system"),
  models: () => request<ModelsResponse>("/api/v1/models"),
};
