/** Telegram WebApp runtime surface (single source of truth). */
export interface TelegramWebApp {
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
