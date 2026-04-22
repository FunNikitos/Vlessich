"""Shared helpers for bot handlers.

Provides narrowing utilities so handlers can access ``cb.message`` without
``# type: ignore`` — aiogram 3 types ``CallbackQuery.message`` as
``Message | InaccessibleMessage | None`` and only ``Message`` supports
``.answer(...)`` reliably.
"""
from __future__ import annotations

from aiogram.types import CallbackQuery, Message, User


def resolve_cb(cb: CallbackQuery) -> tuple[User, Message] | None:
    """Return ``(user, message)`` if both are accessible, else ``None``.

    Use at the top of every ``callback_query`` handler that needs to reply
    with a new message::

        resolved = resolve_cb(cb)
        if resolved is None:
            await cb.answer()
            return
        user, message = resolved
        await message.answer(...)
    """
    user = cb.from_user
    message = cb.message
    if user is None or not isinstance(message, Message):
        return None
    return user, message
