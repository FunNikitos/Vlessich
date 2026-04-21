/** Helpers to read Telegram WebApp runtime data (initData, start_param, user). */

interface TelegramWebApp {
  ready: () => void;
  expand: () => void;
  setHeaderColor: (c: string) => void;
  setBackgroundColor: (c: string) => void;
  initData: string;
  initDataUnsafe: {
    user?: { id: number; username?: string; first_name?: string };
    start_param?: string;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

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
  return { id: u.id, username: u.username, firstName: u.first_name };
}
