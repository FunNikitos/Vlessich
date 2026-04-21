"""Unit tests for ``app.security.verify_internal_signature``.

Run with full toolchain: ``pytest api/tests/test_security.py``.
"""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault(
    "API_DATABASE_URL", "postgresql+asyncpg://vlessich:vlessich@localhost:5432/vlessich"
)

import hashlib
import hmac
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.security import _compute_signature

SECRET = b"x" * 32


def _sign(method: str, path: str, body: bytes, ts: int | None = None) -> dict[str, str]:
    if ts is None:
        ts = int(time.time())
    sig = _compute_signature(SECRET, method, path, ts, body)
    return {"x-vlessich-ts": str(ts), "x-vlessich-sig": sig}


@pytest.mark.asyncio
async def test_missing_signature_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/internal/trials", json={"tg_id": 1})
    # FastAPI returns 422 when required Header is absent — both 401 and 422
    # mean the request was correctly refused before reaching business logic.
    assert r.status_code in (401, 422)


@pytest.mark.asyncio
async def test_bad_signature_rejected() -> None:
    body = b'{"tg_id":1,"phone_e164":"+79991112233","ip_hash":"00"}'
    headers = _sign("POST", "/internal/trials", body)
    headers["x-vlessich-sig"] = "f" * 64  # tamper
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/internal/trials", content=body, headers=headers)
    assert r.status_code == 401
    assert r.json()["code"] == "bad_signature"


@pytest.mark.asyncio
async def test_stale_timestamp_rejected() -> None:
    body = b"{}"
    headers = _sign("POST", "/internal/trials", body, ts=int(time.time()) - 3600)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/internal/trials", content=body, headers=headers)
    assert r.status_code == 401
    assert r.json()["code"] == "bad_signature"


def test_signature_helper_matches_bot_format() -> None:
    """Lock the wire format so bot/api stay in sync."""
    body = b'{"tg_id":1}'
    ts = 1700000000
    expected = hmac.new(
        SECRET, b"POST\n/internal/trials\n1700000000\n" + body, hashlib.sha256
    ).hexdigest()
    assert _compute_signature(SECRET, "POST", "/internal/trials", ts, body) == expected
