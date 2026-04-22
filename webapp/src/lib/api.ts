/** Typed API client for Vlessich Mini-App backend. */
import { getInitData } from "./initData";

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

export interface BootstrapResponse {
  user: { tg_id: number; username: string | null; first_name: string | null };
  subscription: SubscriptionSummary | null;
}

export interface SubscriptionSummary {
  id: string;
  plan: string;
  status: "ACTIVE" | "TRIAL" | "EXPIRED" | "REVOKED";
  expires_at: string | null;
  adblock: boolean;
  smart_routing: boolean;
}

export interface DeviceOut {
  id: string;
  name: string | null;
  last_seen: string | null;
  ip_hash_short: string | null;
}

export interface SubscriptionResponse {
  id: string;
  plan: string;
  status: "ACTIVE" | "TRIAL" | "EXPIRED" | "REVOKED";
  expires_at: string | null;
  sub_token: string;
  urls: { v2ray: string; clash: string; singbox: string; surge: string; raw: string };
  devices: DeviceOut[];
  devices_limit: number;
  adblock: boolean;
  smart_routing: boolean;
}

export interface ToggleResponse {
  adblock: boolean;
  smart_routing: boolean;
}

export interface DeviceResetResponse {
  device_id: string;
  new_uuid_suffix: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      "x-telegram-initdata": getInitData(),
      ...(init?.headers ?? {}),
    },
  });
  const text = await res.text();
  let data: unknown = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (err) {
      throw new ApiError(res.status, "bad_json", `non-JSON response: ${err}`);
    }
  }
  if (!res.ok) {
    const obj = (data ?? {}) as { code?: string; message?: string };
    throw new ApiError(
      res.status,
      String(obj.code ?? "unknown"),
      String(obj.message ?? "Ошибка"),
    );
  }
  return data as T;
}

export const api = {
  bootstrap: () => request<BootstrapResponse>("/v1/webapp/bootstrap"),
  subscription: () => request<SubscriptionResponse>("/v1/webapp/subscription"),
  toggleRouting: (body: { adblock?: boolean; smart_routing?: boolean }) =>
    request<ToggleResponse>("/v1/webapp/subscription/toggle", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  resetDevice: (deviceId: string) =>
    request<DeviceResetResponse>(`/v1/webapp/devices/${deviceId}/reset`, {
      method: "POST",
    }),
};
