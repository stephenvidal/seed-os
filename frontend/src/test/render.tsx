import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { ThemeProvider } from "../lib/theme";

/** `raw` is sent as is, for routes that return files rather than JSON. */
type Route = { status: number; body?: unknown; raw?: string };

/** Stubs fetch by "METHOD path" so tests exercise the real api client and error mapping. */
export function mockApi(routes: Record<string, Route | (() => Route)>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const key = `${init?.method ?? "GET"} ${String(input)}`;
    const r = routes[key];
    const route = typeof r === "function" ? r() : r;
    if (!route) throw new TypeError(`unmocked ${key}`);
    if (route.raw !== undefined) return new Response(route.raw, { status: route.status });
    return new Response(route.body === undefined ? null : JSON.stringify(route.body), {
      status: route.status,
    });
  });
}

export function renderApp(ui: ReactNode, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}
