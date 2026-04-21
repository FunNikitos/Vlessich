"""Unit tests for pure helpers (no DB/Redis required).

Integration flows for /internal/trials, /internal/codes/activate and
/internal/mtproto/issue live in ``test_flows_integration.py`` (opt-in;
requires a running Postgres instance or testcontainers).
"""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)

from app.routers.mtproto import _deeplink
from app.routers.trials import _fingerprint


def test_fingerprint_deterministic() -> None:
    a = _fingerprint("+79991112233", 42, "salt")
    b = _fingerprint("+79991112233", 42, "salt")
    assert a == b
    assert len(a) == 64


def test_fingerprint_changes_with_any_input() -> None:
    base = _fingerprint("+79991112233", 42, "salt")
    assert _fingerprint("+79991112244", 42, "salt") != base
    assert _fingerprint("+79991112233", 43, "salt") != base
    assert _fingerprint("+79991112233", 42, "other") != base


def test_mtproto_deeplink_format() -> None:
    dl = _deeplink("mtp.example.com", 443, "ab" * 16, "www.google.com")
    assert dl.startswith("tg://proxy?server=mtp.example.com&port=443&secret=ee")
    # cloak is appended as hex after the 32-hex secret
    assert dl.endswith("www.google.com".encode().hex())
