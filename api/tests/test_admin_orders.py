"""Stage 11 admin orders endpoint tests.

Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported (uses the real
ASGI app + Postgres). Bot HTTP push is replaced with an in-process
``aiohttp.ClientSession`` stub so ``bot.refund_star_payment`` is never
actually called.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

if "VLESSICH_INTEGRATION_DB" not in os.environ:
    pytest.skip("integration DB not configured", allow_module_level=True)

os.environ["API_DATABASE_URL"] = os.environ["VLESSICH_INTEGRATION_DB"]
os.environ.setdefault(
    "API_BILLING_REFUND_BOT_NOTIFY_URL",
    "http://bot:8081/internal/refund/star_payment",
)

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.auth.admin import Role, create_access_token  # noqa: E402
from app.db import get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Order, Plan, Subscription, User  # noqa: E402
from app.routers.admin import orders as admin_orders  # noqa: E402


def _bearer(role: str) -> dict[str, str]:
    token = create_access_token("integ-orders-admin", cast(Role, role))
    return {"Authorization": f"Bearer {token}"}


async def _seed_user(tg_id: int) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        existing = await s.scalar(select(User).where(User.tg_id == tg_id))
        if existing is None:
            async with s.begin():
                s.add(User(tg_id=tg_id))


async def _seed_plan(code: str, days: int, price: int) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        existing = await s.scalar(select(Plan).where(Plan.code == code))
        if existing is None:
            async with s.begin():
                s.add(
                    Plan(
                        code=code,
                        duration_days=days,
                        price_xtr=price,
                        currency="XTR",
                        is_active=True,
                    )
                )


async def _seed_paid_order(
    *, tg_id: int, plan_code: str, charge_id: str
) -> uuid.UUID:
    """Insert a fully PAID order + matching ACTIVE Subscription."""
    sm = get_sessionmaker()
    order_id = uuid.uuid4()
    sub_id = uuid.uuid4()
    now = datetime.now(UTC)
    async with sm() as s, s.begin():
        s.add(
            Order(
                id=order_id,
                user_id=tg_id,
                plan_code=plan_code,
                amount_xtr=100,
                currency="XTR",
                status="PAID",
                invoice_payload=str(order_id),
                telegram_payment_charge_id=charge_id,
                paid_at=now,
            )
        )
        s.add(
            Subscription(
                id=sub_id,
                user_id=tg_id,
                plan=plan_code,
                started_at=now,
                expires_at=now + timedelta(days=30),
                devices_limit=1,
                adblock=True,
                smart_routing=True,
                status="ACTIVE",
                sub_url_token=f"tok-{order_id.hex}",
                last_order_id=order_id,
            )
        )
    return order_id


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b'{"ok":true}') -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body.decode()

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _FakeClientSession:
    """Captures POST calls; returns the configured response."""

    def __init__(self, status: int = 200) -> None:
        self.calls: list[tuple[str, dict[str, str], bytes]] = []
        self._status = status

    async def __aenter__(self) -> "_FakeClientSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> _FakeResponse:
        self.calls.append((url, headers, data))
        return _FakeResponse(self._status)


def _patch_bot_session(monkeypatch: pytest.MonkeyPatch, status: int = 200) -> _FakeClientSession:
    fake = _FakeClientSession(status=status)

    def _factory(*_a: Any, **_kw: Any) -> _FakeClientSession:
        return fake

    monkeypatch.setattr(admin_orders.aiohttp, "ClientSession", _factory)
    return fake


@pytest.mark.asyncio
async def test_list_orders_filters_by_status() -> None:
    await _seed_user(1010001)
    await _seed_plan("admlist1m", 30, 100)
    await _seed_paid_order(tg_id=1010001, plan_code="admlist1m", charge_id="chg-list-1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            "/admin/orders?status=PAID&user_id=1010001",
            headers=_bearer("readonly"),
        )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["total"] >= 1
    assert all(item["status"] == "PAID" for item in payload["items"])
    assert all(item["user_id"] == 1010001 for item in payload["items"])


@pytest.mark.asyncio
async def test_get_order_returns_detail() -> None:
    await _seed_user(1010002)
    await _seed_plan("admget1m", 30, 100)
    order_id = await _seed_paid_order(
        tg_id=1010002, plan_code="admget1m", charge_id="chg-get-1"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(f"/admin/orders/{order_id}", headers=_bearer("support"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(order_id)
    assert body["telegram_payment_charge_id"] == "chg-get-1"


@pytest.mark.asyncio
async def test_refund_two_phase_calls_bot_then_marks_refunded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _patch_bot_session(monkeypatch, status=200)

    await _seed_user(1010003)
    await _seed_plan("admref1m", 30, 100)
    order_id = await _seed_paid_order(
        tg_id=1010003, plan_code="admref1m", charge_id="chg-ref-ok"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            f"/admin/orders/{order_id}/refund", headers=_bearer("superadmin")
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order_id"] == str(order_id)
    assert body["subscription_revoked"] is True

    # Bot was called exactly once with the charge id in the JSON body.
    assert len(fake.calls) == 1
    url, headers, data = fake.calls[0]
    assert url.endswith("/internal/refund/star_payment")
    assert b"chg-ref-ok" in data
    assert "x-vlessich-sig" in headers

    # DB transitioned.
    sm = get_sessionmaker()
    async with sm() as s:
        order = await s.scalar(select(Order).where(Order.id == order_id))
        sub = await s.scalar(
            select(Subscription).where(Subscription.last_order_id == order_id)
        )
    assert order.status == "REFUNDED"
    assert sub is None  # last_order_id cleared on revoke


@pytest.mark.asyncio
async def test_refund_bot_failure_keeps_order_paid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_bot_session(monkeypatch, status=502)

    await _seed_user(1010004)
    await _seed_plan("admref1m", 30, 100)
    order_id = await _seed_paid_order(
        tg_id=1010004, plan_code="admref1m", charge_id="chg-ref-fail"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            f"/admin/orders/{order_id}/refund", headers=_bearer("superadmin")
        )
    assert r.status_code == 502, r.text

    sm = get_sessionmaker()
    async with sm() as s:
        order = await s.scalar(select(Order).where(Order.id == order_id))
    assert order.status == "PAID"


@pytest.mark.asyncio
async def test_refund_already_refunded_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_bot_session(monkeypatch, status=200)

    await _seed_user(1010005)
    await _seed_plan("admref1m", 30, 100)
    order_id = await _seed_paid_order(
        tg_id=1010005, plan_code="admref1m", charge_id="chg-ref-twice"
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r1 = await ac.post(
            f"/admin/orders/{order_id}/refund", headers=_bearer("superadmin")
        )
        assert r1.status_code == 200, r1.text
        r2 = await ac.post(
            f"/admin/orders/{order_id}/refund", headers=_bearer("superadmin")
        )
    assert r2.status_code == 409
    assert r2.json()["code"] == "order_already_refunded"


@pytest.mark.asyncio
async def test_refund_requires_superadmin() -> None:
    await _seed_user(1010006)
    await _seed_plan("admref1m", 30, 100)
    order_id = await _seed_paid_order(
        tg_id=1010006, plan_code="admref1m", charge_id="chg-ref-rbac"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            f"/admin/orders/{order_id}/refund", headers=_bearer("support")
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_unknown_order_404() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(f"/admin/orders/{uuid.uuid4()}", headers=_bearer("readonly"))
    assert r.status_code == 404
    assert r.json()["code"] == "order_not_found"
