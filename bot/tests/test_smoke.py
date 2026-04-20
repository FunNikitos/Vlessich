"""Smoke tests for bot wiring (no Telegram network calls)."""
from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("BOT_API_BASE_URL", "http://api:8000")
os.environ.setdefault("BOT_API_INTERNAL_SECRET", "x" * 32)


def test_settings_loads() -> None:
    from app.config import get_settings

    s = get_settings()
    assert s.token.get_secret_value() == "123:test"


def test_dispatcher_builds() -> None:
    from app.config import get_settings
    from app.main import build_dispatcher

    dp = build_dispatcher(get_settings())
    assert dp is not None
