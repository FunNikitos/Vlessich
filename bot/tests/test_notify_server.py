"""Unit tests for the bot's ``/internal/notify/mtproto_rotated`` endpoint.

Uses ``aiohttp.test_utils`` so we don't need a live Telegram bot or
backend. We monkeypatch ``ApiClient`` and the ``Bot`` instance so the
test verifies HMAC handling and DM dispatch flow without I/O.

These tests run unconditionally — pure in-process aiohttp wiring.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("BOT_API_BASE_URL", "http://api:8000")
os.environ.setdefault("BOT_API_INTERNAL_SECRET", "x" * 32)

import orjson
import pytest
from aiogram import Bot
from aiohttp.test_utils import TestClient, TestServer
from typing import cast

from app import notify_server
from app.config import get_settings
from app.services.api_client import MtprotoLink

pytestmark = pytest.mark.asyncio


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, tg_id: int, text: str) -> None:
        self.sent.append((tg_id, text))


class _FakeApi:
    async def __aenter__(self) -> "_FakeApi":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_mtproto(self, *, tg_id: int, scope: str = "shared") -> MtprotoLink:
        return MtprotoLink(
            tg_deeplink=f"tg://proxy?server=mtp&port=443&secret=ee{tg_id:032x}",
            host="mtp.example.com",
            port=443,
        )


def _sign(secret: bytes, *, method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    msg = f"{method}\n{path}\n{ts}\n".encode() + body
    return {
        "x-vlessich-ts": ts,
        "x-vlessich-sig": hmac.new(secret, msg, hashlib.sha256).hexdigest(),
        "content-type": "application/json",
    }


@pytest.fixture
async def client(monkeypatch) -> TestClient:
    settings = get_settings()
    bot = _FakeBot()
    monkeypatch.setattr(notify_server, "ApiClient", _FakeApi)
    app = notify_server.build_app(settings=settings, bot=cast(Bot, bot))
    async with TestClient(TestServer(app)) as c:
        c.app["__bot"] = bot
        yield c


async def test_valid_request_dms_user(client: TestClient) -> None:
    settings = get_settings()
    secret = settings.api_internal_secret.get_secret_value().encode()
    body = orjson.dumps(
        {"event_id": "e1", "scope": "shared", "tg_id": 12345, "emitted_at": ""}
    )
    resp = await client.post(
        settings.internal_notify_path,
        data=body,
        headers=_sign(secret, method="POST", path=settings.internal_notify_path, body=body),
    )
    assert resp.status == 200
    payload: dict[str, Any] = await resp.json()
    assert payload["status"] == "ok"
    bot: _FakeBot = client.app["__bot"]
    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 12345
    assert "tg://proxy" in bot.sent[0][1]


async def test_bad_signature_401(client: TestClient) -> None:
    settings = get_settings()
    body = orjson.dumps(
        {"event_id": "e1", "scope": "shared", "tg_id": 12345, "emitted_at": ""}
    )
    resp = await client.post(
        settings.internal_notify_path,
        data=body,
        headers={
            "x-vlessich-ts": str(int(time.time())),
            "x-vlessich-sig": "deadbeef" * 8,
            "content-type": "application/json",
        },
    )
    assert resp.status == 401


async def test_skewed_ts_401(client: TestClient) -> None:
    settings = get_settings()
    secret = settings.api_internal_secret.get_secret_value().encode()
    body = orjson.dumps(
        {"event_id": "e1", "scope": "shared", "tg_id": 12345, "emitted_at": ""}
    )
    ts = str(int(time.time()) - 600)
    msg = f"POST\n{settings.internal_notify_path}\n{ts}\n".encode() + body
    sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    resp = await client.post(
        settings.internal_notify_path,
        data=body,
        headers={
            "x-vlessich-ts": ts,
            "x-vlessich-sig": sig,
            "content-type": "application/json",
        },
    )
    assert resp.status == 401


async def test_invalid_scope_400(client: TestClient) -> None:
    settings = get_settings()
    secret = settings.api_internal_secret.get_secret_value().encode()
    body = orjson.dumps(
        {"event_id": "e1", "scope": "broadcast", "tg_id": 12345, "emitted_at": ""}
    )
    resp = await client.post(
        settings.internal_notify_path,
        data=body,
        headers=_sign(secret, method="POST", path=settings.internal_notify_path, body=body),
    )
    assert resp.status == 400


async def test_missing_tg_id_400(client: TestClient) -> None:
    settings = get_settings()
    secret = settings.api_internal_secret.get_secret_value().encode()
    body = orjson.dumps({"event_id": "e1", "scope": "shared", "emitted_at": ""})
    resp = await client.post(
        settings.internal_notify_path,
        data=body,
        headers=_sign(secret, method="POST", path=settings.internal_notify_path, body=body),
    )
    assert resp.status == 400
