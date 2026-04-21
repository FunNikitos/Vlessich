"""Pydantic v2 schemas for public/internal APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OkResponse(BaseModel):
    ok: bool = True


class ErrorResponse(BaseModel):
    code: str
    message: str


# ---------------------------------------------------------------------------
# Activation (TZ §5)
# ---------------------------------------------------------------------------
class ActivateCodeIn(BaseModel):
    tg_id: int = Field(..., gt=0)
    code: str = Field(..., min_length=4, max_length=64)
    ip_hash: str | None = Field(default=None, min_length=64, max_length=64)
    referral_source: str | None = Field(default=None, max_length=128)


# ---------------------------------------------------------------------------
# Subscription (unified output for activation / trial / GET)
# ---------------------------------------------------------------------------
SubscriptionStatus = Literal["NONE", "ACTIVE", "TRIAL", "EXPIRED", "REVOKED"]


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: SubscriptionStatus
    plan: str | None = None
    expires_at: datetime | None = None
    sub_token: str | None = None
    sub_url: str | None = None
    devices_limit: int | None = None
    traffic_limit_gb: int | None = None
    traffic_used_gb: float = 0.0


# ---------------------------------------------------------------------------
# Trials (TZ §4.1)
# ---------------------------------------------------------------------------
class TrialIn(BaseModel):
    tg_id: int = Field(..., gt=0)
    phone_e164: str = Field(..., pattern=r"^\+[1-9][0-9]{7,14}$")
    ip_hash: str | None = Field(default=None, min_length=64, max_length=64)
    referral_source: str | None = Field(default=None, max_length=128)


# Legacy flat response (bot client still reads ``created`` + ``expires_at``).
# Kept for backwards-compat until bot is fully migrated to ``SubscriptionOut``.
class TrialOut(BaseModel):
    created: bool
    expires_at: datetime


# ---------------------------------------------------------------------------
# MTProto (TZ §9A)
# ---------------------------------------------------------------------------
class MtprotoIn(BaseModel):
    tg_id: int = Field(..., gt=0)
    scope: Literal["shared", "user"] = "shared"


class MtprotoOut(BaseModel):
    tg_deeplink: str
    host: str
    port: int


# ---------------------------------------------------------------------------
# Mini-App webapp endpoints (Stage 3)
# ---------------------------------------------------------------------------
class WebappUserOut(BaseModel):
    tg_id: int
    username: str | None = None
    first_name: str | None = None


class WebappSubscriptionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan: str
    status: str
    expires_at: datetime | None
    adblock: bool
    smart_routing: bool


class WebappBootstrapOut(BaseModel):
    user: WebappUserOut
    subscription: WebappSubscriptionSummary | None = None


class WebappDeviceOut(BaseModel):
    id: str
    name: str | None
    last_seen: datetime | None
    ip_hash_short: str | None  # first 12 chars only — for display


class WebappSubscriptionOut(BaseModel):
    id: str
    plan: str
    status: str
    expires_at: datetime | None
    sub_token: str
    urls: dict[str, str]
    devices: list[WebappDeviceOut]
    devices_limit: int
    adblock: bool
    smart_routing: bool


class WebappToggleIn(BaseModel):
    adblock: bool | None = None
    smart_routing: bool | None = None


class WebappDeviceResetOut(BaseModel):
    device_id: str
    new_uuid_suffix: str  # last 4 chars only


# ---------------------------------------------------------------------------
# Admin stats + node health (Stage 4 T1)
# ---------------------------------------------------------------------------
class StatsOut(BaseModel):
    users_total: int
    codes_total: int
    codes_unused: int
    subs_active: int
    subs_trial: int
    nodes_total: int
    nodes_healthy: int
    nodes_burned: int
    nodes_maintenance: int
    nodes_stale: int


class HealthProbeOut(BaseModel):
    probed_at: datetime
    ok: bool
    latency_ms: int | None
    error: str | None


class NodeHealthOut(BaseModel):
    node_id: str
    hostname: str
    status: str
    current_ip: str | None
    region: str | None
    last_probe_at: datetime | None
    uptime_24h_pct: float | None  # null if no probes in last 24h
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    recent_probes: list[HealthProbeOut]

