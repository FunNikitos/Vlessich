"""Unit tests for /v1/webapp/bootstrap (dependency-override based)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_BOT_TOKEN", "12345:TEST")

import pytest
from fastapi.testclient import TestClient

from app.auth.telegram import TelegramInitData, get_init_data
from app.db import get_session
from app.main import app


@dataclass
class _FakeUser:
    tg_id: int
    tg_username: str | None


@dataclass
class _FakeSub:
    id: str
    plan: str
    status: str
    expires_at: datetime
    adblock: bool
    smart_routing: bool
    started_at: datetime
    user_id: int


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _FakeSession:
    def __init__(self, user: _FakeUser | None, sub: _FakeSub | None) -> None:
        self._user = user
        self._sub = sub
        self._call = 0

    async def execute(self, _stmt: object) -> _FakeResult:
        self._call += 1
        if self._call == 1:
            return _FakeResult(self._user)
        return _FakeResult(self._sub)


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


def test_bootstrap_user_not_found(client: TestClient) -> None:
    async def session_dep():
        yield _FakeSession(user=None, sub=None)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.get("/v1/webapp/bootstrap")
        assert r.status_code == 404
        assert r.json()["code"] == "user_not_found"
    finally:
        app.dependency_overrides.clear()


def test_bootstrap_user_no_subscription(client: TestClient) -> None:
    user = _FakeUser(tg_id=42, tg_username="alice")

    async def session_dep():
        yield _FakeSession(user=user, sub=None)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.get("/v1/webapp/bootstrap")
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["tg_id"] == 42
        assert body["user"]["username"] == "alice"
        assert body["subscription"] is None
    finally:
        app.dependency_overrides.clear()


def test_bootstrap_with_active_sub(client: TestClient) -> None:
    user = _FakeUser(tg_id=42, tg_username="alice")
    sub = _FakeSub(
        id="00000000-0000-0000-0000-000000000001",
        plan="basic",
        status="ACTIVE",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        adblock=True,
        smart_routing=False,
        started_at=datetime.now(UTC),
        user_id=42,
    )

    async def session_dep():
        yield _FakeSession(user=user, sub=sub)

    app.dependency_overrides[get_init_data] = _override_init
    app.dependency_overrides[get_session] = session_dep
    try:
        r = client.get("/v1/webapp/bootstrap")
        assert r.status_code == 200
        body = r.json()
        assert body["subscription"]["plan"] == "basic"
        assert body["subscription"]["status"] == "ACTIVE"
        assert body["subscription"]["adblock"] is True
        assert body["subscription"]["smart_routing"] is False
    finally:
        app.dependency_overrides.clear()
