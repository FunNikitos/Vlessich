"""HTTP client for Vlessich backend API.

All calls sign outgoing requests with HMAC-SHA256 using the shared secret
(``BOT_API_INTERNAL_SECRET``). Backend verifies the signature; see TZ §11A.3.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import aiohttp
import orjson
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logging import log

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=10.0, connect=3.0)


class ApiError(Exception):
    def __init__(self, status: int, code: str, user_message: str) -> None:
        super().__init__(f"{status} {code}: {user_message}")
        self.status = status
        self.code = code
        self.user_message = user_message


@dataclass(slots=True)
class Subscription:
    sub_url: str
    expires_at: str | None
    plan: str


@dataclass(slots=True)
class TrialResult:
    created: bool
    expires_at: str


@dataclass(slots=True)
class MtprotoLink:
    tg_deeplink: str
    host: str
    port: int


class ApiClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base = str(settings.api_base_url).rstrip("/")
        self._secret = settings.api_internal_secret.get_secret_value().encode()
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> Self:
        self._session = aiohttp.ClientSession(
            timeout=DEFAULT_TIMEOUT,
            json_serialize=lambda v: orjson.dumps(v).decode(),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is not None:
            await self._session.close()

    # ----- public ---------------------------------------------------------

    async def activate_code(self, *, tg_id: int, code: str) -> Subscription:
        data = await self._post("/internal/codes/activate", {"tg_id": tg_id, "code": code})
        return Subscription(
            sub_url=data["sub_url"],
            expires_at=data.get("expires_at"),
            plan=data["plan"],
        )

    async def create_trial(self, *, tg_id: int) -> TrialResult:
        data = await self._post("/internal/trials", {"tg_id": tg_id})
        return TrialResult(created=bool(data["created"]), expires_at=data["expires_at"])

    async def get_subscription(self, *, tg_id: int) -> Subscription:
        data = await self._get(f"/internal/users/{tg_id}/subscription")
        return Subscription(
            sub_url=data["sub_url"],
            expires_at=data.get("expires_at"),
            plan=data["plan"],
        )

    async def get_mtproto(self, *, tg_id: int) -> MtprotoLink:
        data = await self._post("/internal/mtproto/issue", {"tg_id": tg_id})
        return MtprotoLink(
            tg_deeplink=data["tg_deeplink"], host=data["host"], port=int(data["port"])
        )

    # ----- internal -------------------------------------------------------

    def _sign(self, method: str, path: str, body: bytes) -> dict[str, str]:
        ts = str(int(time.time()))
        msg = f"{method}\n{path}\n{ts}\n".encode() + body
        sig = hmac.new(self._secret, msg, hashlib.sha256).hexdigest()
        return {"x-vlessich-ts": ts, "x-vlessich-sig": sig}

    async def _get(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path, body=b"")

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = orjson.dumps(payload)
        return await self._request("POST", path, body=body)

    async def _request(self, method: str, path: str, *, body: bytes) -> dict[str, Any]:
        assert self._session is not None, "ApiClient must be used as async context manager"
        url = f"{self._base}{path}"
        headers = self._sign(method, path, body)
        headers["content-type"] = "application/json"

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.3, max=2.0),
            retry=retry_if_exception_type(aiohttp.ClientConnectionError),
            reraise=True,
        ):
            with attempt:
                async with self._session.request(
                    method, url, data=body or None, headers=headers
                ) as resp:
                    raw = await resp.read()
                    if resp.status >= 500:
                        raise aiohttp.ClientConnectionError(f"upstream {resp.status}")
                    data = orjson.loads(raw) if raw else {}
                    if resp.status >= 400:
                        log.warning("api.error", status=resp.status, code=data.get("code"))
                        raise ApiError(
                            status=resp.status,
                            code=str(data.get("code", "unknown")),
                            user_message=str(data.get("message", "Ошибка. Попробуй позже.")),
                        )
                    return data  # type: ignore[no-any-return]
        raise RuntimeError("unreachable")  # pragma: no cover
