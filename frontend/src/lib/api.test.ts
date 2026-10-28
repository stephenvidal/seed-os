import { describe, expect, it, vi } from "vitest";
import { mockApi } from "../test/render";
import { ApiError, api } from "./api";

describe("api client", () => {
  it("maps typed server errors to ApiError", async () => {
    mockApi({
      "POST /api/v1/auth/login": {
        status: 401,
        body: {
          error: { code: "invalid_credentials", message: "Incorrect username or password." },
        },
      },
    });
    const err = await api.login("admin", "x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 401, code: "invalid_credentials" });
  });

  it("reports an unreachable API distinctly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.me()).rejects.toMatchObject({ code: "network_unreachable", status: 0 });
  });

  it("handles non-JSON error bodies", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html>", { status: 502 }));
    await expect(api.me()).rejects.toMatchObject({ status: 502, code: "http_error" });
  });

  it("echoes the CSRF cookie in X-CSRF-Token", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })));
    document.cookie = "seed_csrf=tok%2Fen";
    try {
      await api.logout();
    } finally {
      document.cookie = "seed_csrf=; max-age=0";
    }
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.headers).toMatchObject({ "X-CSRF-Token": "tok/en" });
    await api.logout();
    expect(fetchMock.mock.calls[1]?.[1]?.headers).not.toHaveProperty("X-CSRF-Token");
  });
});
