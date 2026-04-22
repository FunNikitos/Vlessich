"""Tests for Cloudflare Turnstile captcha verifier (Stage 6).

Pure-Python tests with a fake httpx transport — no network. Covers:

* Secret unset → verify ok regardless of token (dev mode).
* Secret set + missing token → ok=False, reason=missing_token.
* Secret set + siteverify success=true → ok=True.
* Secret set + siteverify success=false → ok=False, reason=siteverify_rejected.
* Secret set + siteverify HTTP error → ok=False, reason=verify_http_error.
"""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

import httpx
import pytest
from pydantic import SecretStr

from app.captcha import TurnstileVerifier
from app.config import Settings


def _settings(secret: str | None) -> Settings:
    overrides: dict[str, object] = {
        "internal_secret": SecretStr("x" * 32),
        "secretbox_key": SecretStr("a" * 64),
    }
    if secret is not None:
        overrides["turnstile_secret"] = SecretStr(secret)
    return Settings.model_validate(overrides)


def _transport(handler):  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_dev_mode_no_secret_always_ok() -> None:
    verifier = TurnstileVerifier(_settings(None))
    res = await verifier.verify(token=None)
    assert res.ok is True
    res2 = await verifier.verify(token="anything")
    assert res2.ok is True
    await verifier.aclose()


@pytest.mark.asyncio
async def test_missing_token_when_secret_set() -> None:
    verifier = TurnstileVerifier(
        _settings("turnstile-secret"),
        client=httpx.AsyncClient(transport=_transport(lambda req: httpx.Response(200))),
    )
    res = await verifier.verify(token=None)
    assert res.ok is False
    assert res.reason == "missing_token"
    res2 = await verifier.verify(token="")
    assert res2.ok is False
    assert res2.reason == "missing_token"
    await verifier.aclose()


@pytest.mark.asyncio
async def test_siteverify_success() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True})

    verifier = TurnstileVerifier(
        _settings("turnstile-secret"),
        client=httpx.AsyncClient(transport=_transport(handler)),
    )
    res = await verifier.verify(token="cf-token", remote_ip="1.2.3.4")
    assert res.ok is True
    await verifier.aclose()


@pytest.mark.asyncio
async def test_siteverify_rejected() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error-codes": ["invalid-input-response"]})

    verifier = TurnstileVerifier(
        _settings("turnstile-secret"),
        client=httpx.AsyncClient(transport=_transport(handler)),
    )
    res = await verifier.verify(token="bad-token")
    assert res.ok is False
    assert res.reason == "siteverify_rejected"
    await verifier.aclose()


@pytest.mark.asyncio
async def test_siteverify_http_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    verifier = TurnstileVerifier(
        _settings("turnstile-secret"),
        client=httpx.AsyncClient(transport=_transport(handler)),
    )
    res = await verifier.verify(token="cf-token")
    assert res.ok is False
    assert res.reason == "verify_http_error"
    await verifier.aclose()


@pytest.mark.asyncio
async def test_siteverify_bad_status() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    verifier = TurnstileVerifier(
        _settings("turnstile-secret"),
        client=httpx.AsyncClient(transport=_transport(handler)),
    )
    res = await verifier.verify(token="cf-token")
    assert res.ok is False
    assert res.reason == "verify_http_error"
    await verifier.aclose()
