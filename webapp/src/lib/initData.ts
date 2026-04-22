/** Helpers to read Telegram WebApp runtime data (initData, start_param, user). */
import type { TelegramWebApp } from "./telegram";

export function getWebApp(): TelegramWebApp | null {
  return window.Telegram?.WebApp ?? null;
}

export function getInitData(): string {
  return getWebApp()?.initData ?? "";
}

export function getStartParam(): string | null {
  const tg = getWebApp();
  if (tg?.initDataUnsafe?.start_param) return tg.initDataUnsafe.start_param;
  // Dev fallback: URL query ?startapp=... or ?token=...
  const params = new URLSearchParams(window.location.search);
  return params.get("startapp") ?? params.get("token");
}

export function getTelegramUser():
  | { id: number; username?: string; firstName?: string }
  | null {
  const u = getWebApp()?.initDataUnsafe?.user;
  if (!u) return null;
  const out: { id: number; username?: string; firstName?: string } = { id: u.id };
  if (u.username !== undefined) out.username = u.username;
  if (u.first_name !== undefined) out.firstName = u.first_name;
  return out;
}
