import { useEffect } from "react";

interface TelegramWebApp {
  ready: () => void;
  expand: () => void;
  setHeaderColor: (c: string) => void;
  setBackgroundColor: (c: string) => void;
  initData: string;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

/** Initialize Telegram Mini-App SDK and apply Spotify-dark theme. */
export function useTelegram(): TelegramWebApp | null {
  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (!tg) return;
    tg.ready();
    tg.expand();
    try {
      tg.setHeaderColor("#121212");
      tg.setBackgroundColor("#121212");
    } catch {
      /* older clients ignore */
    }
  }, []);
  return window.Telegram?.WebApp ?? null;
}
