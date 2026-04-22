/** Admin JWT auth store + claims decode + role hierarchy.
 *
 * Stored in sessionStorage — clears on tab close, smaller XSS surface than
 * localStorage. Shape and ordering of fields are stable for downstream use.
 */
import type { Role } from "./types";

const KEY = "vlessich.admin.jwt";

export interface StoredAuth {
  token: string;
  role: Role;
  email: string;
  exp: number; // unix seconds
}

interface JwtClaims {
  sub: string;
  role: Role;
  iat: number;
  exp: number;
}

const ROLE_RANK: Record<Role, number> = {
  readonly: 1,
  support: 2,
  superadmin: 3,
};

export function hasRole(actual: Role, required: Role): boolean {
  return ROLE_RANK[actual] >= ROLE_RANK[required];
}

function decodeBase64Url(s: string): string {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b64 = (s + pad).replace(/-/g, "+").replace(/_/g, "/");
  if (typeof atob !== "function") {
    throw new Error("base64 decode unavailable");
  }
  return atob(b64);
}

function isRole(v: unknown): v is Role {
  return v === "readonly" || v === "support" || v === "superadmin";
}

export function decodeJwt(token: string): JwtClaims {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("malformed jwt");
  const json = decodeBase64Url(parts[1]);
  const raw: unknown = JSON.parse(json);
  if (typeof raw !== "object" || raw === null) {
    throw new Error("malformed jwt payload");
  }
  const obj = raw as Record<string, unknown>;
  const sub = obj["sub"];
  const role = obj["role"];
  const iat = obj["iat"];
  const exp = obj["exp"];
  if (
    typeof sub !== "string" ||
    !isRole(role) ||
    typeof iat !== "number" ||
    typeof exp !== "number"
  ) {
    throw new Error("malformed jwt claims");
  }
  return { sub, role, iat, exp };
}

export const authStore = {
  get(): StoredAuth | null {
    if (typeof sessionStorage === "undefined") return null;
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    try {
      const parsed: unknown = JSON.parse(raw);
      if (typeof parsed !== "object" || parsed === null) return null;
      const o = parsed as Record<string, unknown>;
      if (
        typeof o["token"] !== "string" ||
        !isRole(o["role"]) ||
        typeof o["email"] !== "string" ||
        typeof o["exp"] !== "number"
      ) {
        return null;
      }
      return {
        token: o["token"],
        role: o["role"],
        email: o["email"],
        exp: o["exp"],
      };
    } catch {
      return null;
    }
  },
  set(auth: StoredAuth): void {
    if (typeof sessionStorage === "undefined") return;
    sessionStorage.setItem(KEY, JSON.stringify(auth));
  },
  clear(): void {
    if (typeof sessionStorage === "undefined") return;
    sessionStorage.removeItem(KEY);
  },
  isExpired(auth: StoredAuth, nowSec: number = Math.floor(Date.now() / 1000)): boolean {
    return auth.exp <= nowSec;
  },
};
