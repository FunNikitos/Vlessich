"""Trials (TZ §4.1) — 1 per user forever."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from app.schemas import TrialIn, TrialOut
from app.security import verify_internal_signature

router = APIRouter(
    prefix="/internal/trials",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


@router.post("", response_model=TrialOut)
async def create_trial(payload: TrialIn) -> TrialOut:
    # TODO: check fingerprint+tg_id collision, insert trials row, provision sub.
    return TrialOut(created=True, expires_at=datetime.now(UTC) + timedelta(days=3))
