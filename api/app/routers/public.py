"""Public Mini-App endpoints (Telegram initData-authenticated).

Stub: real initData validation against BOT_TOKEN; see TZ §7.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["public"])


@router.get("/webapp/bootstrap")
async def bootstrap() -> dict[str, str]:
    return {"status": "todo"}
