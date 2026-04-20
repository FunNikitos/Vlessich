"""Code activation (TZ §5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas import ActivateCodeIn, SubscriptionOut
from app.security import verify_internal_signature

router = APIRouter(
    prefix="/internal/codes",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


@router.post("/activate", response_model=SubscriptionOut)
async def activate(payload: ActivateCodeIn) -> SubscriptionOut:
    # TODO: implement transactional activation:
    #   1) lock code row, validate status/window/reservation
    #   2) create user (if not exists), subscription, sub_url_token
    #   3) provision in Remnawave
    #   4) emit audit event
    return SubscriptionOut(
        sub_url=f"https://sub.example.com/{'x' * 48}",
        plan="TODO",
        expires_at=None,
        devices_limit=3,
    )
