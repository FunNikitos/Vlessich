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


# ---------------------------------------------------------------------------
# Billing / Payments (Stage 11, Telegram Stars MVP)
# ---------------------------------------------------------------------------
class PlanOut(BaseModel):
    code: str
    duration_days: int
    price_xtr: int
    currency: Literal["XTR"]


class PlansListOut(BaseModel):
    plans: list[PlanOut]


class CreateOrderIn(BaseModel):
    tg_id: int = Field(..., gt=0)
    plan_code: str = Field(..., min_length=1, max_length=16)


class CreateOrderOut(BaseModel):
    order_id: str
    invoice_payload: str
    amount_xtr: int
    currency: Literal["XTR"]
    plan_code: str
    duration_days: int


class PrecheckIn(BaseModel):
    invoice_payload: str = Field(..., min_length=1, max_length=128)
    amount_xtr: int = Field(..., gt=0)


class PaymentSuccessIn(BaseModel):
    invoice_payload: str = Field(..., min_length=1, max_length=128)
    amount_xtr: int = Field(..., gt=0)
    telegram_payment_charge_id: str = Field(..., min_length=1, max_length=255)
    provider_payment_charge_id: str | None = Field(default=None, max_length=255)


class PaymentSuccessOut(BaseModel):
    order_id: str
    subscription_id: str
    new_expires_at: datetime


class OrderAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    plan_code: str
    amount_xtr: int
    currency: str
    status: str
    telegram_payment_charge_id: str | None
    provider_payment_charge_id: str | None
    created_at: datetime
    paid_at: datetime | None
    refunded_at: datetime | None


class OrdersListOut(BaseModel):
    items: list[OrderAdminOut]
    total: int


class RefundOut(BaseModel):
    order_id: str
    subscription_revoked: bool


# ---------------------------------------------------------------------------
# Smart-routing (Stage 12)
# ---------------------------------------------------------------------------
RoutingProfileLiteral = Literal["full", "smart", "adblock", "plain"]
RulesetFormatLiteral = Literal["singbox", "clash"]


class SmartRoutingConfigIn(BaseModel):
    """Bot/sub-Worker → API request body for /internal/smart_routing/config."""

    tg_id: int = Field(..., gt=0)
    fmt: RulesetFormatLiteral = "singbox"


class SmartRoutingConfigOut(BaseModel):
    profile: RoutingProfileLiteral
    fmt: RulesetFormatLiteral
    body: str
    ru_count: int
    ads_count: int
    generated_at: datetime


class SetRoutingProfileIn(BaseModel):
    """Bot → API request body to switch a subscription's routing profile."""

    tg_id: int = Field(..., gt=0)
    profile: RoutingProfileLiteral


class SetRoutingProfileOut(BaseModel):
    subscription_id: str
    profile: RoutingProfileLiteral
    adblock: bool
    smart_routing: bool


class RulesetSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    kind: Literal["antifilter", "v2fly_geosite", "custom"]
    url: str | None
    category: Literal["ru", "ads"]
    is_enabled: bool
    last_pulled_at: datetime | None
    last_error: str | None
    current_domain_count: int | None = None


class RulesetSourcesListOut(BaseModel):
    items: list[RulesetSourceOut]


class RulesetSourceCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    kind: Literal["antifilter", "v2fly_geosite", "custom"]
    url: str | None = Field(default=None, max_length=2048)
    category: Literal["ru", "ads"] = "ru"
    is_enabled: bool = True


class RulesetSourceUpdateIn(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    is_enabled: bool | None = None
    category: Literal["ru", "ads"] | None = None


class RulesetSnapshotAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    sha256: str
    domain_count: int
    is_current: bool
    fetched_at: datetime

