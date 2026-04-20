"""Simple in-memory per-user throttling.

Production should move this to Redis; see TZ §5.5 (anti-abuse). This stub
is sufficient for dev and blocks obvious flooders (>1 msg / 0.5s).
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

WINDOW_SECONDS = 0.5


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None:
            now = time.monotonic()
            last = self._last.get(user.id, 0.0)
            if now - last < WINDOW_SECONDS:
                return None
            self._last[user.id] = now
        return await handler(event, data)
