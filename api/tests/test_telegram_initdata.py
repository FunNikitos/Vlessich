"""Tests for ``app.auth.telegram`` initData HMAC verification."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.auth.telegram import (
    INIT_DATA_MAX_AGE_SEC,
    TelegramInitData,
    verify_init_data,
)

BOT_TOKEN = SecretStr("12345:TEST_BOT_TOKEN")


def _sign(fields: dict[str, str], bot_token: SecretStr = BOT_TOKEN) -> str:
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(
        b"WebAppData", bot_token.get_secret_value().encode(), hashlib.sha256
    ).digest()
    sig = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    fields = {**fields, "hash": sig}
    return urlencode(fields)


def _user_json(user_id: int = 42, username: str = "alice") -> str:
    return json.dumps({"id": user_id, "username": username, "first_name": "Alice"})


def test_verify_ok() -> None:
    now = int(time.time())
    raw = _sign(
        {
            "auth_date": str(now),
            "user": _user_json(),
            "start_param": "subtoken123",
        }
    )
    out = verify_init_data(raw, BOT_TOKEN, now=now)
    assert isinstance(out, TelegramInitData)
    assert out.user_id == 42
    assert out.username == "alice"
    assert out.first_name == "Alice"
    assert out.start_param == "subtoken123"
    assert out.auth_date == now


def test_verify_missing_raw() -> None:
    with pytest.raises(HTTPException) as exc:
        verify_init_data("", BOT_TOKEN)
    assert exc.value.status_code == 401


def test_verify_missing_hash() -> None:
    raw = urlencode({"auth_date": "1", "user": _user_json()})
    with pytest.raises(HTTPException) as exc:
        verify_init_data(raw, BOT_TOKEN, now=1)
    assert exc.value.status_code == 401


def test_verify_bad_hash() -> None:
    now = int(time.time())
    raw = _sign({"auth_date": str(now), "user": _user_json()})
    tampered = raw.replace("auth_date=" + str(now), "auth_date=" + str(now + 1))
    with pytest.raises(HTTPException) as exc:
        verify_init_data(tampered, BOT_TOKEN, now=now)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "bad_init_data"


def test_verify_expired() -> None:
    now = int(time.time())
    old = now - INIT_DATA_MAX_AGE_SEC - 10
    raw = _sign({"auth_date": str(old), "user": _user_json()})
    with pytest.raises(HTTPException) as exc:
        verify_init_data(raw, BOT_TOKEN, now=now)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "init_data_expired"


def test_verify_bad_auth_date() -> None:
    raw = _sign({"auth_date": "not-a-number", "user": _user_json()})
    with pytest.raises(HTTPException) as exc:
        verify_init_data(raw, BOT_TOKEN, now=int(time.time()))
    assert exc.value.status_code == 401


def test_verify_missing_user() -> None:
    now = int(time.time())
    raw = _sign({"auth_date": str(now)})
    with pytest.raises(HTTPException) as exc:
        verify_init_data(raw, BOT_TOKEN, now=now)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "bad_init_data"


def test_verify_user_no_id() -> None:
    now = int(time.time())
    raw = _sign(
        {"auth_date": str(now), "user": json.dumps({"username": "no-id"})}
    )
    with pytest.raises(HTTPException) as exc:
        verify_init_data(raw, BOT_TOKEN, now=now)
    assert exc.value.status_code == 401


def test_verify_user_malformed_json() -> None:
    now = int(time.time())
    raw = _sign({"auth_date": str(now), "user": "{not-json"})
    with pytest.raises(HTTPException) as exc:
        verify_init_data(raw, BOT_TOKEN, now=now)
    assert exc.value.status_code == 401


def test_verify_optional_fields_missing() -> None:
    now = int(time.time())
    raw = _sign(
        {"auth_date": str(now), "user": json.dumps({"id": 7})}
    )
    out = verify_init_data(raw, BOT_TOKEN, now=now)
    assert out.user_id == 7
    assert out.username is None
    assert out.first_name is None
    assert out.start_param is None
