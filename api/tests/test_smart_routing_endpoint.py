"""Smart-routing endpoint contract tests (Stage 12)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RulesetSnapshot, RulesetSource, Subscription, User


def _sign(secret: bytes, method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    msg = f"{method}\n{path}\n{ts}\n".encode() + body
    sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return {
        "x-vlessich-ts": ts,
        "x-vlessich-sig": sig,
        "content-type": "application/json",
    }


async def _seed_active_sub(
    session: AsyncSession, tg_id: int, profile: str = "plain"
) -> Subscription:
    user = User(tg_id=tg_id)
    session.add(user)
    await session.flush()
    sub = Subscription(
        id=uuid4(),
        user_id=tg_id,
        plan="stage12-test",
        started_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        devices_limit=3,
        adblock=False,
        smart_routing=False,
        status="ACTIVE",
        sub_url_token="token-" + "x" * 24,
        routing_profile=profile,
    )
    session.add(sub)
    await session.flush()
    return sub


@pytest.mark.asyncio
async def test_config_returns_409_when_disabled(
    async_client: AsyncClient, internal_secret: str
) -> None:
    body = json.dumps({"tg_id": 111, "fmt": "singbox"}).encode()
    headers = _sign(internal_secret.encode(), "POST", "/internal/smart_routing/config", body)
    resp = await async_client.post(
        "/internal/smart_routing/config", content=body, headers=headers
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "smart_routing_disabled"


@pytest.mark.asyncio
async def test_set_profile_flips_bools(
    async_client: AsyncClient,
    session: AsyncSession,
    internal_secret: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("API_SMART_ROUTING_ENABLED", "true")
    get_settings.cache_clear()

    sub = await _seed_active_sub(session, tg_id=222, profile="plain")
    await session.commit()

    body = json.dumps({"tg_id": 222, "profile": "full"}).encode()
    headers = _sign(
        internal_secret.encode(), "POST", "/internal/smart_routing/set_profile", body
    )
    resp = await async_client.post(
        "/internal/smart_routing/set_profile", content=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["profile"] == "full"
    assert data["adblock"] is True
    assert data["smart_routing"] is True

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_config_renders_for_active_sub(
    async_client: AsyncClient,
    session: AsyncSession,
    internal_secret: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("API_SMART_ROUTING_ENABLED", "true")
    get_settings.cache_clear()

    await _seed_active_sub(session, tg_id=333, profile="full")

    src = RulesetSource(
        id=uuid4(),
        name="test-ru",
        kind="antifilter",
        url="https://example.test/list",
        category="ru",
        is_enabled=True,
    )
    session.add(src)
    await session.flush()
    session.add(
        RulesetSnapshot(
            id=uuid4(),
            source_id=src.id,
            sha256="a" * 64,
            domain_count=1,
            raw="sber.ru\n",
            is_current=True,
            fetched_at=datetime.now(UTC),
        )
    )
    await session.commit()

    body = json.dumps({"tg_id": 333, "fmt": "singbox"}).encode()
    headers = _sign(
        internal_secret.encode(), "POST", "/internal/smart_routing/config", body
    )
    resp = await async_client.post(
        "/internal/smart_routing/config", content=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["profile"] == "full"
    assert data["fmt"] == "singbox"
    assert "sber.ru" in data["body"]
    assert data["ru_count"] >= 1

    get_settings.cache_clear()
