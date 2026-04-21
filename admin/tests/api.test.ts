import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api";
import { authStore } from "@/lib/auth";

const FETCH = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", FETCH);
  sessionStorage.clear();
});

afterEach(() => {
  FETCH.mockReset();
  vi.unstubAllGlobals();
});

function ok<T>(body: T): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function err(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ code, message }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("api.login", () => {
  it("posts without auth header and returns body", async () => {
    FETCH.mockResolvedValueOnce(
      ok({ access_token: "tok", role: "superadmin" }),
    );
    const out = await api.login({ email: "a@b", password: "p" });
    expect(out.access_token).toBe("tok");
    const init = FETCH.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["authorization"]).toBeUndefined();
  });
});

describe("api.stats", () => {
  it("attaches bearer token from authStore", async () => {
    authStore.set({ token: "T", role: "readonly", email: "a", exp: 9999999999 });
    FETCH.mockResolvedValueOnce(
      ok({
        users_total: 1,
        codes_total: 0,
        codes_unused: 0,
        subs_active: 0,
        subs_trial: 0,
        nodes_total: 0,
        nodes_healthy: 0,
        nodes_burned: 0,
        nodes_maintenance: 0,
        nodes_stale: 0,
      }),
    );
    await api.stats();
    const init = FETCH.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["authorization"]).toBe(
      "Bearer T",
    );
  });
});

describe("error handling", () => {
  it("throws ApiError with code/message", async () => {
    authStore.set({ token: "T", role: "readonly", email: "a", exp: 9999999999 });
    FETCH.mockResolvedValueOnce(err(404, "node_not_found", "no node"));
    await expect(api.nodes.health("x")).rejects.toBeInstanceOf(ApiError);
    try {
      await api.nodes.health("x");
    } catch (e) {
      const err = e as ApiError;
      expect(err.status).toBe(404);
      expect(err.code).toBe("node_not_found");
    }
  });

  it("clears auth on 401", async () => {
    authStore.set({ token: "T", role: "readonly", email: "a", exp: 9999999999 });
    FETCH.mockResolvedValueOnce(err(401, "bad_signature", "expired"));
    // jsdom location.assign — replace via stub.
    const assignSpy = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign: assignSpy, pathname: "/" },
      writable: true,
    });
    await expect(api.stats()).rejects.toBeInstanceOf(ApiError);
    expect(authStore.get()).toBeNull();
    expect(assignSpy).toHaveBeenCalledWith("/login");
  });
});

describe("query building", () => {
  it("omits undefined/null/empty filters", async () => {
    authStore.set({ token: "T", role: "readonly", email: "a", exp: 9999999999 });
    FETCH.mockResolvedValueOnce(ok({ total: 0, items: [] }));
    await api.codes.list({ status: undefined, plan: "1m", page: 1 });
    const url = FETCH.mock.calls[0][0] as string;
    expect(url).toContain("plan=1m");
    expect(url).toContain("page=1");
    expect(url).not.toContain("status=");
  });
});
