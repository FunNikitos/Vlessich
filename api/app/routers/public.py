"""Public Mini-App endpoints (stub).

Real endpoints live in :mod:`app.routers.webapp` (Stage 3) authenticated via
Telegram ``initData``. This module is kept as a placeholder for future
unauthenticated public endpoints (e.g. health of webapp API).
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/v1/public", tags=["public"])

