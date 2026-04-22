"""Smoke tests for Stage 12 /config handler wiring."""
from __future__ import annotations

import inspect
import os

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("BOT_API_BASE_URL", "http://api:8000")
os.environ.setdefault("BOT_API_INTERNAL_SECRET", "x" * 32)

from app.handlers import config as config_handler
from app.texts import (
    CONFIG_API_ERROR,
    CONFIG_DISABLED,
    CONFIG_NO_SUB,
    CONFIG_PROFILE_LABEL,
    CONFIG_PROFILE_SET,
    CONFIG_PROFILE_SET_NO_LINK,
    CONFIG_PROMPT,
)


def test_router_and_handlers() -> None:
    assert config_handler.router.name == "config"
    for fn in (
        config_handler.config_cmd,
        config_handler.config_callback,
        config_handler.config_set,
    ):
        assert inspect.iscoroutinefunction(fn)


def test_profiles_kb_has_four_rows() -> None:
    kb = config_handler._profiles_kb()
    assert len(kb.inline_keyboard) == 4
    codes = [row[0].callback_data.removeprefix("cfg:set:") for row in kb.inline_keyboard]
    assert set(codes) == {"full", "smart", "adblock", "plain"}
    for row in kb.inline_keyboard:
        btn = row[0]
        code = btn.callback_data.removeprefix("cfg:set:")
        assert btn.text == CONFIG_PROFILE_LABEL[code]


def test_profile_labels_cover_all_profiles() -> None:
    assert set(CONFIG_PROFILE_LABEL.keys()) == {"full", "smart", "adblock", "plain"}
    for v in CONFIG_PROFILE_LABEL.values():
        assert v.strip()


def test_text_invariants() -> None:
    assert "{label}" in CONFIG_PROFILE_SET
    assert "{singbox_url}" in CONFIG_PROFILE_SET
    assert "{clash_url}" in CONFIG_PROFILE_SET
    assert "{label}" in CONFIG_PROFILE_SET_NO_LINK
    assert "{message}" in CONFIG_API_ERROR
    for s in (CONFIG_DISABLED, CONFIG_NO_SUB, CONFIG_PROMPT):
        assert s.strip()


def test_format_links_respects_base_url(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("BOT_SUB_WORKER_BASE_URL", "https://sub.example.com/")
    get_settings.cache_clear()
    try:
        sb, cl = config_handler._format_links("tok123")
        assert sb == "https://sub.example.com/tok123?fmt=singbox"
        assert cl == "https://sub.example.com/tok123?fmt=clash"
    finally:
        get_settings.cache_clear()


def test_format_links_none_when_unset(monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.delenv("BOT_SUB_WORKER_BASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        sb, cl = config_handler._format_links("tok123")
        assert sb is None and cl is None
    finally:
        get_settings.cache_clear()


def test_profiles_constant() -> None:
    assert config_handler.PROFILES == ("full", "smart", "adblock", "plain")
