"""Root router — wires feature routers.

Router composition keeps handler modules small and testable. See TZ §5-9 for
flows (activation, subscription, smart-routing, mtproto).
"""
from __future__ import annotations

from aiogram import Router

from app.handlers import activation, common, mtproto, purchase, subscription, trial

router = Router(name="root")
router.include_router(common.router)
router.include_router(activation.router)
router.include_router(trial.router)
router.include_router(subscription.router)
router.include_router(mtproto.router)
router.include_router(purchase.router)

__all__ = ["router"]
