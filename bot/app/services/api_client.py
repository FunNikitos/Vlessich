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
    status: str  # NONE | ACTIVE | TRIAL | EXPIRED | REVOKED
    plan: str | None
    expires_at: str | None
    sub_token: str | None


@dataclass(slots=True)
class MtprotoLink:
    tg_deeplink: str
    host: str
    port: int


@dataclass(slots=True)
class PlanInfo:
    code: str
    duration_days: int
    price_xtr: int
    currency: str


@dataclass(slots=True)
class OrderDraft:
    order_id: str
    invoice_payload: str
    amount_xtr: int
    currency: str
    plan_code: str
    duration_days: int


@dataclass(slots=True)
class PaymentSuccessAck:
    order_id: str
    subscription_id: str
    new_expires_at: str | None


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

    async def activate_code(
        self,
        *,
        tg_id: int,
        code: str,
        ip_hash: str | None = None,
        referral_source: str | None = None,
    ) -> Subscription:
        body: dict[str, Any] = {"tg_id": tg_id, "code": code}
        if ip_hash is not None:
            body["ip_hash"] = ip_hash
        if referral_source is not None:
            body["referral_source"] = referral_source
        data = await self._post("/internal/codes/activate", body)
        return _parse_subscription(data)

    async def create_trial(
        self,
        *,
        tg_id: int,
        phone_e164: str,
        ip_hash: str | None = None,
        referral_source: str | None = None,
    ) -> Subscription:
        body: dict[str, Any] = {"tg_id": tg_id, "phone_e164": phone_e164}
        if ip_hash is not None:
            body["ip_hash"] = ip_hash
        if referral_source is not None:
            body["referral_source"] = referral_source
        data = await self._post("/internal/trials", body)
        return _parse_subscription(data)

    async def get_subscription(self, *, tg_id: int) -> Subscription:
        data = await self._get(f"/internal/users/{tg_id}/subscription")
        return _parse_subscription(data)

    async def get_mtproto(self, *, tg_id: int, scope: str = "shared") -> MtprotoLink:
        data = await self._post(
            "/internal/mtproto/issue", {"tg_id": tg_id, "scope": scope}
        )
        return MtprotoLink(
            tg_deeplink=str(data["tg_deeplink"]),
            host=str(data["host"]),
            port=int(data["port"]),
        )

    # ----- billing (Stage 11) ---------------------------------------------

    async def list_plans(self) -> list[PlanInfo]:
        data = await self._post("/internal/payments/plans", {})
        plans_raw = data.get("plans", [])
        if not isinstance(plans_raw, list):
            return []
        out: list[PlanInfo] = []
        for entry in plans_raw:
            if not isinstance(entry, dict):
                continue
            try:
                out.append(
                    PlanInfo(
                        code=str(entry["code"]),
                        duration_days=int(entry["duration_days"]),
                        price_xtr=int(entry["price_xtr"]),
                        currency=str(entry.get("currency", "XTR")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out

    async def create_order(self, *, tg_id: int, plan_code: str) -> OrderDraft:
        data = await self._post(
            "/internal/payments/create_order",
            {"tg_id": tg_id, "plan_code": plan_code},
        )
        return OrderDraft(
            order_id=str(data["order_id"]),
            invoice_payload=str(data["invoice_payload"]),
            amount_xtr=int(data["amount_xtr"]),
            currency=str(data.get("currency", "XTR")),
            plan_code=str(data["plan_code"]),
            duration_days=int(data["duration_days"]),
        )

    async def precheck_order(self, *, invoice_payload: str, amount_xtr: int) -> bool:
        data = await self._post(
            "/internal/payments/precheck",
            {"invoice_payload": invoice_payload, "amount_xtr": amount_xtr},
        )
        return bool(data.get("ok", False))

    async def notify_payment_success(
        self,
        *,
        invoice_payload: str,
        amount_xtr: int,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None,
    ) -> PaymentSuccessAck:
        body: dict[str, Any] = {
            "invoice_payload": invoice_payload,
            "amount_xtr": amount_xtr,
            "telegram_payment_charge_id": telegram_payment_charge_id,
        }
        if provider_payment_charge_id is not None:
            body["provider_payment_charge_id"] = provider_payment_charge_id
        data = await self._post("/internal/payments/success", body)
        return PaymentSuccessAck(
            order_id=str(data["order_id"]),
            subscription_id=str(data["subscription_id"]),
            new_expires_at=_opt_str(data.get("new_expires_at")),
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
                    parsed: Any = orjson.loads(raw) if raw else {}
                    if not isinstance(parsed, dict):
                        raise ApiError(
                            status=resp.status,
                            code="malformed_response",
                            user_message="Ошибка. Попробуй позже.",
                        )
                    data: dict[str, Any] = parsed
                    if resp.status >= 400:
                        log.warning("api.error", status=resp.status, code=data.get("code"))
                        raise ApiError(
                            status=resp.status,
                            code=str(data.get("code", "unknown")),
                            user_message=str(data.get("message", "Ошибка. Попробуй позже.")),
                        )
                    return data
        raise RuntimeError("unreachable")  # pragma: no cover


def _parse_subscription(data: dict[str, Any]) -> Subscription:
    return Subscription(
        status=str(data.get("status", "NONE")),
        plan=_opt_str(data.get("plan")),
        expires_at=_opt_str(data.get("expires_at")),
        sub_token=_opt_str(data.get("sub_token")),
    )


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)
