"""Cloudflare Turnstile verification helper (Stage 6).

Captcha is **optional**: when ``settings.turnstile_secret`` is ``None``
(dev mode) the verifier short-circuits to success and logs it once per
process.

The verify client is an injectable singleton so tests can patch the
httpx client with a fake.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog

from app.config import Settings

log = structlog.get_logger("captcha")


@dataclass(slots=True, frozen=True)
class CaptchaResult:
    ok: bool
    reason: str | None


class CaptchaVerifier(Protocol):
    async def verify(
        self, token: str | None, *, remote_ip: str | None = None
    ) -> CaptchaResult: ...


class TurnstileVerifier:
    """Calls Cloudflare Turnstile ``siteverify``.

    Behaviour:
    - secret is ``None``            → always ok (dev mode, token ignored).
    - token is empty / missing      → ok=False, reason="missing_token".
    - siteverify HTTP error         → ok=False, reason="verify_http_error".
    - siteverify returns success=F  → ok=False, reason="siteverify_rejected".
    """

    def __init__(
        self, settings: Settings, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(timeout=5.0)

    async def verify(
        self, token: str | None, *, remote_ip: str | None = None
    ) -> CaptchaResult:
        secret = self._settings.turnstile_secret
        if secret is None:
            return CaptchaResult(ok=True, reason=None)
        if not token:
            return CaptchaResult(ok=False, reason="missing_token")
        payload = {"secret": secret.get_secret_value(), "response": token}
        if remote_ip:
            payload["remoteip"] = remote_ip
        try:
            resp = await self._client.post(
                self._settings.turnstile_verify_url, data=payload
            )
        except httpx.HTTPError as exc:
            log.warning("captcha.verify_http_error", error=str(exc))
            return CaptchaResult(ok=False, reason="verify_http_error")
        if resp.status_code != 200:
            log.warning("captcha.verify_bad_status", status=resp.status_code)
            return CaptchaResult(ok=False, reason="verify_http_error")
        data = resp.json()
        if data.get("success") is True:
            return CaptchaResult(ok=True, reason=None)
        return CaptchaResult(
            ok=False,
            reason="siteverify_rejected",
        )

    async def aclose(self) -> None:
        await self._client.aclose()


_verifier: CaptchaVerifier | None = None


def get_captcha_verifier(settings: Settings) -> CaptchaVerifier:
    """Module-level singleton; replace via ``set_captcha_verifier`` in tests."""
    global _verifier
    if _verifier is None:
        _verifier = TurnstileVerifier(settings)
    return _verifier


def set_captcha_verifier(verifier: CaptchaVerifier | None) -> None:
    """Test seam: inject a fake, or reset to ``None`` to rebuild default."""
    global _verifier
    _verifier = verifier


__all__ = [
    "CaptchaResult",
    "CaptchaVerifier",
    "TurnstileVerifier",
    "get_captcha_verifier",
    "set_captcha_verifier",
]
