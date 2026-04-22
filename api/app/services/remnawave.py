"""Remnawave client interface + in-memory mock + HTTP implementation.

The business layer depends only on the ``RemnawaveClient`` ABC. Selection
between mock (dev/test) and HTTP (staging/prod) is driven by
``settings.remnawave_mode``.

Contract notes:
- ``sub_token`` is opaque; Mini-App queries sub-Worker with it to fetch the
  actual subscription URL. We return a 64-char hex token here.
- Remna user id is the provider's internal handle; we store it in
  ``subscriptions.remna_user_id`` for later extend/revoke calls.
- HTTP implementation retries on 5xx/timeout (3 attempts, exponential
  back-off) and surfaces the original exception otherwise. No silent
  fallbacks.
"""
from __future__ import annotations

import abc
import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID

import httpx

from app.config import get_settings


@dataclass(slots=True, frozen=True)
class RemnaUser:
    remna_user_id: str
    sub_token: str
    expires_at: datetime


class RemnawaveError(RuntimeError):
    """Provider-side failure surfaced to callers."""


class RemnawaveClient(abc.ABC):
    @abc.abstractmethod
    async def create_user(
        self, subscription_id: UUID, plan: str, ttl_days: int
    ) -> RemnaUser: ...

    @abc.abstractmethod
    async def extend_user(self, remna_user_id: str, ttl_days: int) -> datetime: ...

    @abc.abstractmethod
    async def revoke_user(self, remna_user_id: str) -> None: ...

    @abc.abstractmethod
    async def get_subscription_url(self, remna_user_id: str) -> str: ...


@dataclass(slots=True)
class _MockRecord:
    remna_user_id: str
    sub_token: str
    plan: str
    expires_at: datetime
    revoked: bool = False


@dataclass(slots=True)
class MockRemnawaveClient(RemnawaveClient):
    """In-memory mock. State is per-instance — inject a singleton via DI."""

    _by_user: dict[str, _MockRecord] = field(default_factory=dict)

    async def create_user(
        self, subscription_id: UUID, plan: str, ttl_days: int
    ) -> RemnaUser:
        if ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        remna_user_id = f"remna-{subscription_id}"
        sub_token = secrets.token_hex(32)
        expires_at = datetime.now(UTC) + timedelta(days=ttl_days)
        self._by_user[remna_user_id] = _MockRecord(
            remna_user_id=remna_user_id,
            sub_token=sub_token,
            plan=plan,
            expires_at=expires_at,
        )
        return RemnaUser(
            remna_user_id=remna_user_id, sub_token=sub_token, expires_at=expires_at
        )

    async def extend_user(self, remna_user_id: str, ttl_days: int) -> datetime:
        record = self._by_user.get(remna_user_id)
        if record is None or record.revoked:
            raise KeyError(f"remna user {remna_user_id} not found")
        base = max(record.expires_at, datetime.now(UTC))
        record.expires_at = base + timedelta(days=ttl_days)
        return record.expires_at

    async def revoke_user(self, remna_user_id: str) -> None:
        record = self._by_user.get(remna_user_id)
        if record is None:
            return
        record.revoked = True

    async def get_subscription_url(self, remna_user_id: str) -> str:
        record = self._by_user.get(remna_user_id)
        if record is None or record.revoked:
            raise KeyError(f"remna user {remna_user_id} not found")
        return f"https://sub.example.com/{record.sub_token}"


_MOCK_SINGLETON = MockRemnawaveClient()


@dataclass(slots=True)
class HTTPRemnawaveClient(RemnawaveClient):
    """Real HTTP client against a Remnawave-compatible provider.

    The endpoint shapes mirror Remnawave's REST surface:
      POST   /api/users               → create
      PATCH  /api/users/{id}/extend   → extend
      DELETE /api/users/{id}          → revoke
      GET    /api/users/{id}/sub-url  → subscription URL

    Real Remnawave routes may differ in casing/paths; the HTTP layer is
    isolated here so a single patch suffices when we lock the provider.
    """

    base_url: str
    api_key: str
    timeout: float = 10.0
    max_retries: int = 3
    _client: httpx.AsyncClient | None = None

    def _client_or_new(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        client = self._client_or_new()
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = await client.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                await asyncio.sleep(0.2 * (2**attempt))
                continue
            if resp.status_code >= 500:
                last_exc = RemnawaveError(f"5xx from remnawave: {resp.status_code}")
                await asyncio.sleep(0.2 * (2**attempt))
                continue
            return resp
        raise RemnawaveError(
            f"remnawave {method} {path} failed after {self.max_retries} attempts"
        ) from last_exc

    async def create_user(
        self, subscription_id: UUID, plan: str, ttl_days: int
    ) -> RemnaUser:
        if ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        resp = await self._request(
            "POST",
            "/api/users",
            json={
                "external_id": str(subscription_id),
                "plan": plan,
                "ttl_days": ttl_days,
            },
        )
        if resp.status_code >= 400:
            raise RemnawaveError(f"create_user: {resp.status_code} {resp.text}")
        data = resp.json()
        return RemnaUser(
            remna_user_id=data["id"],
            sub_token=data["sub_token"],
            expires_at=_parse_iso(data["expires_at"]),
        )

    async def extend_user(self, remna_user_id: str, ttl_days: int) -> datetime:
        resp = await self._request(
            "PATCH",
            f"/api/users/{remna_user_id}/extend",
            json={"ttl_days": ttl_days},
        )
        if resp.status_code == 404:
            raise KeyError(f"remna user {remna_user_id} not found")
        if resp.status_code >= 400:
            raise RemnawaveError(f"extend_user: {resp.status_code} {resp.text}")
        return _parse_iso(resp.json()["expires_at"])

    async def revoke_user(self, remna_user_id: str) -> None:
        resp = await self._request("DELETE", f"/api/users/{remna_user_id}")
        if resp.status_code in (200, 204, 404):
            return
        raise RemnawaveError(f"revoke_user: {resp.status_code} {resp.text}")

    async def get_subscription_url(self, remna_user_id: str) -> str:
        resp = await self._request("GET", f"/api/users/{remna_user_id}/sub-url")
        if resp.status_code == 404:
            raise KeyError(f"remna user {remna_user_id} not found")
        if resp.status_code >= 400:
            raise RemnawaveError(f"get_subscription_url: {resp.status_code} {resp.text}")
        return str(resp.json()["url"])

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _parse_iso(value: str) -> datetime:
    """Parse RFC3339/ISO8601, normalizing trailing ``Z`` to ``+00:00``."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@lru_cache(maxsize=1)
def _http_singleton() -> HTTPRemnawaveClient:
    settings = get_settings()
    if settings.remnawave_token is None:
        raise RuntimeError(
            "API_REMNAWAVE_TOKEN must be set when API_REMNAWAVE_MODE=http"
        )
    return HTTPRemnawaveClient(
        base_url=settings.remnawave_url,
        api_key=settings.remnawave_token.get_secret_value(),
    )


def get_remnawave() -> RemnawaveClient:
    """FastAPI dependency. Switch by ``settings.remnawave_mode``."""
    mode = get_settings().remnawave_mode
    if mode == "http":
        return _http_singleton()
    return _MOCK_SINGLETON
