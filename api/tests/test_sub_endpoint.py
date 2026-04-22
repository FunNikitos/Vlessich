"""Tests for ``GET /internal/sub/{token}`` (Stage 2 T1)."""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault(
    "API_DATABASE_URL", "postgresql+asyncpg://vlessich:vlessich@localhost:5432/vlessich"
)

import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.security import _compute_signature

SECRET = b"x" * 32


def _sign(path: str, ts: int | None = None) -> dict[str, str]:
    if ts is None:
        ts = int(time.time())
    sig = _compute_signature(SECRET, "GET", path, ts, b"")
    return {"x-vlessich-ts": str(ts), "x-vlessich-sig": sig}


@pytest.mark.asyncio
async def test_sub_token_too_short_404() -> None:
    path = "/internal/sub/short"
    headers = _sign(path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(path, headers=headers)
    assert r.status_code == 404
    assert r.json()["code"] == "no_active_subscription"


@pytest.mark.asyncio
async def test_sub_unsigned_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/internal/sub/" + "a" * 32)
    assert r.status_code in (401, 422)


@pytest.mark.asyncio
async def test_sub_bad_signature_rejected() -> None:
    path = "/internal/sub/" + "a" * 32
    headers = _sign(path)
    headers["x-vlessich-sig"] = "f" * 64
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(path, headers=headers)
    assert r.status_code == 401
    assert r.json()["code"] == "bad_signature"
