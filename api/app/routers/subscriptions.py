"""Subscription (Mini-App) — placeholder."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/v1/subscription", tags=["public"])


@router.get("")
async def me() -> dict[str, str]:
    # TODO: extract user from Telegram initData, return subscription view.
    return {"status": "todo"}
