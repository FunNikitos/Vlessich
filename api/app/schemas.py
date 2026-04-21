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
