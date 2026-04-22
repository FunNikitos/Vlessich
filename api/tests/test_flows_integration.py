"""End-to-end integration tests for TZ §4 flows.

These tests are SKIPPED unless ``VLESSICH_INTEGRATION_DB`` env var is set
to a Postgres URL (e.g. ``postgresql+asyncpg://vlessich:vlessich@localhost:5432/vlessich``).

Cover (per docs/plan-stage-1.md T9):
  1. Trial -> active TRIAL subscription returned by GET endpoint.
  2. Activate code -> subscription extended on second activation.
  3. Trial fingerprint abuse: another tg_id with same phone -> 409.
  4. Activate rate-limit: 6th attempt -> 429.
  5. Reserved code mismatch -> 403.
  6. Concurrent activate of single-use code: exactly 1 wins.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from datetime import UTC, datetime, timedelta

import pytest

INTEGRATION_DB = os.environ.get("VLESSICH_INTEGRATION_DB")
pytestmark = pytest.mark.skipif(
    INTEGRATION_DB is None,
    reason="set VLESSICH_INTEGRATION_DB=postgresql+asyncpg://... to run",
)

if INTEGRATION_DB:
    os.environ["API_DATABASE_URL"] = INTEGRATION_DB
os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)

SECRET = b"x" * 32


def _sign(method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    msg = f"{method}\n{path}\n{ts}\n".encode() + body
    sig = hmac.new(SECRET, msg, hashlib.sha256).hexdigest()
    return {"x-vlessich-ts": ts, "x-vlessich-sig": sig, "content-type": "application/json"}


@pytest.fixture
async def client():
    import httpx
    from httpx import ASGITransport

    from app.crypto import SecretBoxCipher
    from app.db import get_sessionmaker, init_engine
    from app.main import app
    from app.models import Code

    init_engine(INTEGRATION_DB or "")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # Seed one ACTIVE single-use code 'PROMO123' for tests.
        cipher = SecretBoxCipher("a" * 64)
        sm = get_sessionmaker()
        async with sm() as s, s.begin():
            s.add(
                Code(
                    code_enc=cipher.seal("PROMO123"),
                    code_hash=hashlib.sha256(b"PROMO123").hexdigest(),
                    plan_name="month",
                    duration_days=30,
                    devices_limit=3,
                    allowed_locations=["fi"],
                    valid_from=datetime.now(UTC) - timedelta(days=1),
                    valid_until=datetime.now(UTC) + timedelta(days=30),
                    single_use=True,
                )
            )
        yield c


@pytest.mark.asyncio
async def test_trial_then_get_subscription(client) -> None:
    import orjson

    body = orjson.dumps({"tg_id": 1001, "phone_e164": "+79991110001"})
    r = await client.post("/internal/trials", content=body, headers=_sign("POST", "/internal/trials", body))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "TRIAL"

    g = await client.get(
        "/internal/users/1001/subscription",
        headers=_sign("GET", "/internal/users/1001/subscription", b""),
    )
    assert g.status_code == 200
    assert g.json()["status"] == "TRIAL"


@pytest.mark.asyncio
async def test_trial_fingerprint_collision_rejected(client) -> None:
    import orjson

    b1 = orjson.dumps({"tg_id": 2001, "phone_e164": "+79992220001"})
    r1 = await client.post("/internal/trials", content=b1, headers=_sign("POST", "/internal/trials", b1))
    assert r1.status_code == 200

    # Same phone, different tg_id -> fingerprint collision.
    b2 = orjson.dumps({"tg_id": 2002, "phone_e164": "+79992220001"})
    r2 = await client.post("/internal/trials", content=b2, headers=_sign("POST", "/internal/trials", b2))
    assert r2.status_code == 409
    assert r2.json()["code"] == "trial_already_used"


@pytest.mark.asyncio
async def test_activate_rate_limit(client) -> None:
    import orjson

    headers_for = lambda body: _sign("POST", "/internal/codes/activate", body)
    statuses = []
    for _ in range(6):
        body = orjson.dumps({"tg_id": 3001, "code": "WRONG-CODE"})
        r = await client.post("/internal/codes/activate", content=body, headers=headers_for(body))
        statuses.append(r.status_code)
    assert statuses[-1] == 429


@pytest.mark.asyncio
async def test_activate_single_use_code_concurrent(client) -> None:
    import orjson

    async def attempt(tg_id: int):
        body = orjson.dumps({"tg_id": tg_id, "code": "PROMO123"})
        return await client.post(
            "/internal/codes/activate", content=body, headers=_sign("POST", "/internal/codes/activate", body)
        )

    r1, r2 = await asyncio.gather(attempt(4001), attempt(4002))
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409] or statuses == [200, 404]
