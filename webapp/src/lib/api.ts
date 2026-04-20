/** API client for Vlessich backend (Mini-App side). */
const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const initData = window.Telegram?.WebApp?.initData ?? "";
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      "x-telegram-initdata": initData,
      ...(init?.headers ?? {}),
    },
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) {
    throw new ApiError(
      res.status,
      String(data.code ?? "unknown"),
      String(data.message ?? "Ошибка"),
    );
  }
  return data as T;
}

export const api = {
  bootstrap: () => request<{ status: string }>("/v1/webapp/bootstrap"),
  subscription: () => request<{ status: string }>("/v1/subscription"),
};
