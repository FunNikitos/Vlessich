/** Admin API client. Auth via Cloudflare Zero Trust (см. TZ §11A). */
const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) {
    throw new ApiError(res.status, String(data.code ?? "unknown"), String(data.message ?? "Ошибка"));
  }
  return data as T;
}

export const api = {
  stats: () => request<{ users: number; codes: number; subs: number }>("/admin/stats"),
  codes: () => request<{ items: unknown[] }>("/admin/codes"),
  users: () => request<{ items: unknown[] }>("/admin/users"),
  nodes: () => request<{ items: unknown[] }>("/admin/nodes"),
};
