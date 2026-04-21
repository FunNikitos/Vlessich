/** Auth context + provider + hook. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import { authStore, decodeJwt } from "@/lib/auth";
import type { StoredAuth } from "@/lib/auth";

interface AuthContextValue {
  auth: StoredAuth | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<StoredAuth | null>(() => {
    const stored = authStore.get();
    if (!stored) return null;
    if (authStore.isExpired(stored)) {
      authStore.clear();
      return null;
    }
    return stored;
  });

  // Auto-logout on token expiry.
  useEffect(() => {
    if (!auth) return;
    const ms = Math.max(0, auth.exp * 1000 - Date.now());
    const id = window.setTimeout(() => {
      authStore.clear();
      setAuth(null);
    }, ms);
    return () => window.clearTimeout(id);
  }, [auth]);

  const login = useCallback(async (email: string, password: string) => {
    const out = await api.login({ email, password });
    const claims = decodeJwt(out.access_token);
    const next: StoredAuth = {
      token: out.access_token,
      role: out.role,
      email,
      exp: claims.exp,
    };
    authStore.set(next);
    setAuth(next);
  }, []);

  const logout = useCallback(() => {
    authStore.clear();
    setAuth(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ auth, login, logout }),
    [auth, login, logout],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used within AuthProvider");
  return v;
}
