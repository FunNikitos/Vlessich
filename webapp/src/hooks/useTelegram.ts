import { useEffect } from "react";
import type { TelegramWebApp } from "@/lib/telegram";

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
