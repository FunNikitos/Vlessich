"""Tests for /v1/webapp/subscription/toggle and /v1/webapp/devices/{id}/reset."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_BOT_TOKEN", "12345:TEST")

import pytest
from fastapi.testclient import TestClient

from app.auth.telegram import TelegramInitData, get_init_data
from app.db import get_session
from app.main import app
from app.routers import webapp as webapp_router


@dataclass
class _FakeSub:
    id: uuid.UUID
    plan: str = "basic"
    status: str = "ACTIVE"
    expires_at: datetime | None = None
    sub_url_token: str = "tok123"
    devices_limit: int = 3
    adblock: bool = True
    smart_routing: bool = True
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_id: int = 42


@dataclass
class _FakeDevice:
    id: uuid.UUID
    subscription_id: uuid.UUID
    xray_uuid_enc: bytes = b""
    name: str | None = None
    last_seen: datetime | None = None
    ip_hash: str | None = None


class _Result:
    def __init__(self, value: object) -> None:
        self._v = value

    def scalar_one_or_none(self) -> object:
        return self._v


class _SessionForToggle:
    def __init__(self, sub: _FakeSub | None) -> None:
        self._sub = sub
        self.added: list[object] = []

    async def execute(self, _stmt: object) -> _Result:
        return _Result(self._sub)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def begin(self):
        outer = self

        class _Tx:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *args: object) -> bool:
                return False

        return _Tx()


class _SessionForReset:
    def __init__(self, device: _FakeDevice | None, sub: _FakeSub | None) -> None:
        self._device = device
        self._sub = sub
        self._call = 0
        self.added: list[object] = []

    async def execute(self, _stmt: object) -> _Result:
        self._call += 1
        if self._call == 1:
            return _Result(self._device)
        return _Result(self._sub)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def begin(self):
        outer = self

        class _Tx:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *args: object) -> bool:
                return False

        return _Tx()


def _override_init() -> TelegramInitData:
    return TelegramInitData(
        user_id=42,
        username="alice",
        first_name="Alice",
        auth_date=int(datetime.now(UTC).timestamp()),
        start_param=None,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Patch sliding_window_check to always allow (no Redis in unit tests)
    monkeypatch.setattr(
        webapp_router, "sliding_window_check", AsyncMock(return_value=True)
    )

    class _Cipher:
        def seal(self, value: str) -> bytes:
            return value.encode()

    monkeypatch.setattr(webapp_router, "get_cipher", lambda: _Cipher())
    return TestClient(app)


def test_toggle_requires_at_least_one_field(client: TestClient) -> None:
    sub = _FakeSub(id=uuid.uuid4())

    async def session_dep():
        yield _SessionForToggle(sub=sub)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.post("/v1/webapp/subscription/toggle", json={})
        assert r.status_code == 422
        assert r.json()["code"] == "invalid_request"
    finally:
        app.dependency_overrides.clear()


def test_toggle_updates_fields(client: TestClient) -> None:
    sub = _FakeSub(id=uuid.uuid4(), adblock=False, smart_routing=True)

    async def session_dep():
        yield _SessionForToggle(sub=sub)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.post(
            "/v1/webapp/subscription/toggle", json={"adblock": True, "smart_routing": False}
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"adblock": True, "smart_routing": False}
        assert sub.adblock is True
        assert sub.smart_routing is False
    finally:
        app.dependency_overrides.clear()


def test_toggle_no_active_subscription(client: TestClient) -> None:
    async def session_dep():
        yield _SessionForToggle(sub=None)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.post("/v1/webapp/subscription/toggle", json={"adblock": True})
        assert r.status_code == 404
        assert r.json()["code"] == "no_active_subscription"
    finally:
        app.dependency_overrides.clear()


def test_reset_device_owner_mismatch(client: TestClient) -> None:
    dev_id = uuid.uuid4()
    sub_id = uuid.uuid4()
    device = _FakeDevice(id=dev_id, subscription_id=sub_id)
    sub = _FakeSub(id=sub_id, user_id=999)

    async def session_dep():
        yield _SessionForReset(device=device, sub=sub)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.post(f"/v1/webapp/devices/{dev_id}/reset")
        assert r.status_code == 403
        assert r.json()["code"] == "forbidden"
    finally:
        app.dependency_overrides.clear()


def test_reset_device_ok(client: TestClient) -> None:
    dev_id = uuid.uuid4()
    sub_id = uuid.uuid4()
    device = _FakeDevice(id=dev_id, subscription_id=sub_id)
    sub = _FakeSub(id=sub_id, user_id=42)

    async def session_dep():
        yield _SessionForReset(device=device, sub=sub)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.post(f"/v1/webapp/devices/{dev_id}/reset")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["device_id"] == str(dev_id)
        assert len(body["new_uuid_suffix"]) == 4
        assert device.xray_uuid_enc != b""
    finally:
        app.dependency_overrides.clear()


def test_reset_device_rate_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        webapp_router, "sliding_window_check", AsyncMock(return_value=False)
    )
    dev_id = uuid.uuid4()

    async def session_dep():
        yield _SessionForReset(device=None, sub=None)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.post(f"/v1/webapp/devices/{dev_id}/reset")
        assert r.status_code == 429
        assert r.json()["code"] == "rate_limited"
    finally:
        app.dependency_overrides.clear()
