/** Typed admin API client. JWT Bearer + 401 → redirect /login. */
import { authStore } from "./auth";
import type {
  AuditListOut,
  CodeBatchCreateIn,
  CodeBatchCreateOut,
  CodeListOut,
  LoginIn,
  LoginOut,
  NodeCreateIn,
  NodeHealthOut,
  NodeOut,
  NodePatchIn,
  StatsOut,
  SubscriptionAdminOut,
  SubscriptionListOut,
  UserListOut,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api") as string;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  query?: Record<string, string | number | undefined | null>;
  body?: unknown;
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  skipAuth?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json",
  };
  if (!opts.skipAuth) {
    const auth = authStore.get();
    if (auth) headers["authorization"] = `Bearer ${auth.token}`;
  }
  const res = await fetch(buildUrl(path, opts.query), {
    method: opts.method ?? (opts.body ? "POST" : "GET"),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  const text = await res.text();
  let data: unknown = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { code: "bad_response", message: text };
    }
  }
  if (!res.ok) {
    if (res.status === 401 && !opts.skipAuth) {
      authStore.clear();
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    const obj = (typeof data === "object" && data !== null
      ? (data as Record<string, unknown>)
      : {}) as Record<string, unknown>;
    const code = typeof obj["code"] === "string" ? obj["code"] : "unknown";
    const message =
      typeof obj["message"] === "string" ? obj["message"] : "Ошибка";
    throw new ApiError(res.status, code, message);
  }
  return data as T;
}

export const api = {
  login(body: LoginIn): Promise<LoginOut> {
    return request<LoginOut>("/admin/auth/login", { body, skipAuth: true });
  },
  stats(): Promise<StatsOut> {
    return request<StatsOut>("/admin/stats");
  },
  codes: {
    list(query: {
      status?: string;
      plan?: string;
      page?: number;
      limit?: number;
    }): Promise<CodeListOut> {
      return request<CodeListOut>("/admin/codes", { query });
    },
    create(body: CodeBatchCreateIn): Promise<CodeBatchCreateOut> {
      return request<CodeBatchCreateOut>("/admin/codes", { body });
    },
    revoke(id: string): Promise<void> {
      return request<void>(`/admin/codes/${id}`, { method: "DELETE" });
    },
  },
  users: {
    list(query: {
      tg_id?: number;
      page?: number;
      limit?: number;
    }): Promise<UserListOut> {
      return request<UserListOut>("/admin/users", { query });
    },
  },
  subscriptions: {
    list(query: {
      status?: string;
      plan?: string;
      user_id?: number;
      page?: number;
      limit?: number;
    }): Promise<SubscriptionListOut> {
      return request<SubscriptionListOut>("/admin/subscriptions", { query });
    },
    revoke(id: string): Promise<SubscriptionAdminOut> {
      return request<SubscriptionAdminOut>(
        `/admin/subscriptions/${id}/revoke`,
        { method: "POST" },
      );
    },
  },
  audit: {
    list(query: {
      action?: string;
      actor_type?: string;
      page?: number;
      limit?: number;
    }): Promise<AuditListOut> {
      return request<AuditListOut>("/admin/audit", { query });
    },
  },
  nodes: {
    list(): Promise<NodeOut[]> {
      return request<NodeOut[]>("/admin/nodes");
    },
    create(body: NodeCreateIn): Promise<NodeOut> {
      return request<NodeOut>("/admin/nodes", { body });
    },
    patch(id: string, body: NodePatchIn): Promise<NodeOut> {
      return request<NodeOut>(`/admin/nodes/${id}`, { method: "PATCH", body });
    },
    health(id: string): Promise<NodeHealthOut> {
      return request<NodeHealthOut>(`/admin/nodes/${id}/health`);
    },
  },
};
