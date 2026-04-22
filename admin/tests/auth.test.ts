import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { authStore, decodeJwt, hasRole } from "@/lib/auth";

// Pre-built tokens (HS256, dummy signature). Payloads:
//  - valid: {sub:"u1", role:"superadmin", iat:0, exp:9999999999}
//  - support: {sub:"u2", role:"support", iat:0, exp:1}
const TOKEN_SUPER =
  "header." +
  btoa(
    JSON.stringify({ sub: "u1", role: "superadmin", iat: 0, exp: 9999999999 }),
  )
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_") +
  ".sig";

const TOKEN_SUPPORT_EXPIRED =
  "header." +
  btoa(JSON.stringify({ sub: "u2", role: "support", iat: 0, exp: 1 }))
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_") +
  ".sig";

describe("hasRole", () => {
  it("allows higher rank to access lower required", () => {
    expect(hasRole("superadmin", "readonly")).toBe(true);
    expect(hasRole("support", "readonly")).toBe(true);
  });
  it("rejects lower rank for higher required", () => {
    expect(hasRole("readonly", "support")).toBe(false);
    expect(hasRole("support", "superadmin")).toBe(false);
  });
  it("self-equal allowed", () => {
    expect(hasRole("support", "support")).toBe(true);
  });
});

describe("decodeJwt", () => {
  it("parses valid token claims", () => {
    const c = decodeJwt(TOKEN_SUPER);
    expect(c.sub).toBe("u1");
    expect(c.role).toBe("superadmin");
    expect(c.exp).toBe(9999999999);
  });
  it("throws on malformed token", () => {
    expect(() => decodeJwt("notatoken")).toThrow();
  });
  it("throws on bad role", () => {
    const bad =
      "h." +
      btoa(JSON.stringify({ sub: "x", role: "owner", iat: 0, exp: 1 }))
        .replace(/=+$/, "")
        .replace(/\+/g, "-")
        .replace(/\//g, "_") +
      ".s";
    expect(() => decodeJwt(bad)).toThrow();
  });
});

describe("authStore", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => sessionStorage.clear());

  it("set + get round-trip", () => {
    authStore.set({
      token: TOKEN_SUPER,
      role: "superadmin",
      email: "a@b",
      exp: 9999999999,
    });
    const got = authStore.get();
    expect(got?.email).toBe("a@b");
    expect(got?.role).toBe("superadmin");
  });

  it("returns null for missing", () => {
    expect(authStore.get()).toBeNull();
  });

  it("returns null for malformed json", () => {
    sessionStorage.setItem("vlessich.admin.jwt", "{not-json");
    expect(authStore.get()).toBeNull();
  });

  it("clear removes entry", () => {
    authStore.set({
      token: TOKEN_SUPER,
      role: "superadmin",
      email: "a@b",
      exp: 9999999999,
    });
    authStore.clear();
    expect(authStore.get()).toBeNull();
  });

  it("isExpired true for past exp", () => {
    expect(
      authStore.isExpired(
        {
          token: TOKEN_SUPPORT_EXPIRED,
          role: "support",
          email: "a@b",
          exp: 1,
        },
        9999,
      ),
    ).toBe(true);
  });

  it("isExpired false for future exp", () => {
    expect(
      authStore.isExpired(
        {
          token: TOKEN_SUPER,
          role: "superadmin",
          email: "a@b",
          exp: 9999999999,
        },
        1000,
      ),
    ).toBe(false);
  });
});
