"""Tests for GET /v1/webapp/subscription (dependency-override)."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_BOT_TOKEN", "12345:TEST")
os.environ.setdefault("API_SUB_WORKER_BASE_URL", "https://sub.example.com")

import pytest
from fastapi.testclient import TestClient

from app.auth.telegram import TelegramInitData, get_init_data
from app.db import get_session
from app.main import app


@dataclass
class _FakeSub:
    id: uuid.UUID
    plan: str
    status: str
    expires_at: datetime | None
    sub_url_token: str
    devices_limit: int
    adblock: bool
    smart_routing: bool
    started_at: datetime
    user_id: int


@dataclass
class _FakeDevice:
    id: uuid.UUID
    subscription_id: uuid.UUID
    name: str | None = None
    last_seen: datetime | None = None
    ip_hash: str | None = None


class _ScalarsResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def all(self) -> list[object]:
        return self._items


class _FakeResult:
    def __init__(self, *, value: object = None, items: list[object] | None = None) -> None:
        self._value = value
        self._items = items

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalars(self) -> _ScalarsResult:
        return _ScalarsResult(self._items or [])


class _FakeSession:
    def __init__(self, sub: _FakeSub | None, devices: list[_FakeDevice]) -> None:
        self._sub = sub
        self._devices = devices
        self._call = 0

    async def execute(self, _stmt: object) -> _FakeResult:
        self._call += 1
        if self._call == 1:
            return _FakeResult(value=self._sub)
        return _FakeResult(items=list(self._devices))


def _override_init() -> TelegramInitData:
    return TelegramInitData(
        user_id=42,
        username="alice",
        first_name="Alice",
        auth_date=int(datetime.now(UTC).timestamp()),
        start_param=None,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_subscription_404_when_missing(client: TestClient) -> None:
    async def session_dep():
        yield _FakeSession(sub=None, devices=[])

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.get("/v1/webapp/subscription")
        assert r.status_code == 404
        assert r.json()["code"] == "no_active_subscription"
    finally:
        app.dependency_overrides.clear()


def test_subscription_returns_urls_and_devices(client: TestClient) -> None:
    sub_id = uuid.uuid4()
    sub = _FakeSub(
        id=sub_id,
        plan="basic",
        status="ACTIVE",
        expires_at=datetime.now(UTC) + timedelta(days=10),
        sub_url_token="abcdef1234567890",
        devices_limit=3,
        adblock=True,
        smart_routing=False,
        started_at=datetime.now(UTC),
        user_id=42,
    )
    devices = [
        _FakeDevice(
            id=uuid.uuid4(),
            subscription_id=sub_id,
            name="iphone",
            ip_hash="f" * 64,
        ),
    ]

    async def session_dep():
        yield _FakeSession(sub=sub, devices=devices)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.get("/v1/webapp/subscription")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sub_token"] == "abcdef1234567890"
        assert set(body["urls"]) == {"v2ray", "clash", "singbox", "surge", "raw"}
        assert body["urls"]["clash"].endswith("?client=clash")
        assert body["devices"][0]["name"] == "iphone"
        assert body["devices"][0]["ip_hash_short"] == "f" * 12
    finally:
        app.dependency_overrides.clear()
