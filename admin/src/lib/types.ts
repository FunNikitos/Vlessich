/** Shared DTO types — mirror backend pydantic models. */

export type Role = "superadmin" | "support" | "readonly";

export type CodeStatus = "ACTIVE" | "USED" | "REVOKED" | "EXPIRED";
export type SubscriptionStatus = "ACTIVE" | "TRIAL" | "EXPIRED" | "REVOKED";
export type NodeStatus = "HEALTHY" | "BURNED" | "MAINTENANCE";
export type ActorType = "system" | "admin" | "user" | "bot";

export interface LoginIn {
  email: string;
  password: string;
  captcha_token?: string | null;
}

export interface LoginOut {
  access_token: string;
  role: Role;
}

export interface StatsOut {
  users_total: number;
  codes_total: number;
  codes_unused: number;
  subs_active: number;
  subs_trial: number;
  nodes_total: number;
  nodes_healthy: number;
  nodes_burned: number;
  nodes_maintenance: number;
  nodes_stale: number;
}

export interface CodeOut {
  id: string;
  plan_name: string;
  duration_days: number;
  devices_limit: number;
  status: CodeStatus;
  valid_from: string;
  valid_until: string;
  reserved_for_tg_id: number | null;
  tag: string | null;
  note: string | null;
  created_at: string;
}

export interface CodeListOut {
  total: number;
  items: CodeOut[];
}

export interface CodeBatchCreateIn {
  plan_name: string;
  duration_days: number;
  devices_limit: number;
  count: number;
  valid_days?: number;
  allowed_locations: string[];
  tag?: string | null;
  note?: string | null;
  reserved_for_tg_id?: number | null;
  traffic_limit_gb?: number | null;
  adblock_default?: boolean;
  smart_routing_default?: boolean;
  single_use?: boolean;
}

export interface CodeBatchCreateOut {
  created: number;
  codes: string[];
}

export interface UserOut {
  tg_id: number;
  tg_username: string | null;
  lang: string;
  phone_e164: string | null;
  referral_source: string | null;
  banned: boolean;
  created_at: string;
}

export interface UserListOut {
  total: number;
  items: UserOut[];
}

export interface SubscriptionAdminOut {
  id: string;
  user_id: number;
  plan: string;
  status: SubscriptionStatus;
  started_at: string;
  expires_at: string | null;
  devices_limit: number;
}

export interface SubscriptionListOut {
  total: number;
  items: SubscriptionAdminOut[];
}

export interface AuditOut {
  id: string;
  actor_type: ActorType;
  actor_ref: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  at: string;
}

export interface AuditListOut {
  total: number;
  items: AuditOut[];
}

export interface NodeOut {
  id: string;
  hostname: string;
  current_ip: string | null;
  provider: string | null;
  region: string | null;
  status: NodeStatus;
  last_probe_at: string | null;
  created_at: string;
}

export interface NodeCreateIn {
  hostname: string;
  current_ip?: string | null;
  provider?: string | null;
  region?: string | null;
  status?: NodeStatus;
}

export interface NodePatchIn {
  current_ip?: string | null;
  status?: NodeStatus | null;
  region?: string | null;
}

export interface HealthProbeOut {
  probed_at: string;
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
}

export interface NodeHealthOut {
  node_id: string;
  hostname: string;
  status: NodeStatus;
  current_ip: string | null;
  region: string | null;
  last_probe_at: string | null;
  uptime_24h_pct: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  recent_probes: HealthProbeOut[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
}
