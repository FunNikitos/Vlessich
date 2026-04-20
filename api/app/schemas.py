"""Pydantic v2 schemas for public/internal APIs."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OkResponse(BaseModel):
    ok: bool = True


class ErrorResponse(BaseModel):
    code: str
    message: str


class ActivateCodeIn(BaseModel):
    tg_id: int = Field(..., gt=0)
    code: str = Field(..., pattern=r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sub_url: str
    plan: str
    expires_at: datetime | None = None
    devices_limit: int
    traffic_limit_gb: int | None = None
    traffic_used_gb: float = 0.0


class TrialIn(BaseModel):
    tg_id: int = Field(..., gt=0)


class TrialOut(BaseModel):
    created: bool
    expires_at: datetime


class MtprotoIn(BaseModel):
    tg_id: int = Field(..., gt=0)


class MtprotoOut(BaseModel):
    tg_deeplink: str
    host: str
    port: int
